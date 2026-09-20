import { Camera, CameraResultType, CameraSource, type GalleryPhoto, type Photo } from '@capacitor/camera'
import { Capacitor } from '@capacitor/core'
import { createDomFilePicker, type RuntimeFileCapabilities, type RuntimeFileSource } from '@lamtools/ui/app/runtime'

export const DEVICE_REQUEST_DENIED_MESSAGE = '设备拒绝了您的请求'

const domPicker = createDomFilePicker()

function isGranted(state: string | undefined): boolean {
  return state === 'granted' || state === 'limited'
}

function isPickerCancellation(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /cancel(?:led|ed)|canceled|user cancelled/i.test(message)
}

async function requestSourcePermission(source: RuntimeFileSource): Promise<void> {
  if (source !== 'camera' && source !== 'photos') return
  try {
    const permission = source === 'camera' ? 'camera' : 'photos'
    const status = await Camera.requestPermissions({ permissions: [permission] })
    if (!isGranted(status[permission])) throw new Error(DEVICE_REQUEST_DENIED_MESSAGE)
  } catch (error) {
    if (error instanceof Error && error.message === DEVICE_REQUEST_DENIED_MESSAGE) throw error
    throw new Error(DEVICE_REQUEST_DENIED_MESSAGE, { cause: error })
  }
}

function extensionFor(format: string | undefined): string {
  const normalized = (format || 'jpeg').toLowerCase()
  return normalized === 'jpg' ? 'jpeg' : normalized
}

async function nativePhotoToFile(photo: Pick<Photo, 'webPath' | 'format'> | GalleryPhoto, index: number): Promise<File> {
  if (!photo.webPath) throw new Error(DEVICE_REQUEST_DENIED_MESSAGE)
  try {
    const response = await fetch(photo.webPath)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const format = extensionFor(photo.format)
    const type = blob.type || `image/${format}`
    return new File([blob], `lamtools-${Date.now()}-${index + 1}.${format}`, { type })
  } catch (error) {
    throw new Error(DEVICE_REQUEST_DENIED_MESSAGE, { cause: error })
  }
}

async function pickNativePhotos(): Promise<File[] | null> {
  try {
    await requestSourcePermission('photos')
    const result = await Camera.pickImages({ quality: 90 })
    if (!result.photos.length) return null
    return Promise.all(result.photos.map(nativePhotoToFile))
  } catch (error) {
    if (isPickerCancellation(error)) return null
    if (error instanceof Error && error.message === DEVICE_REQUEST_DENIED_MESSAGE) throw error
    throw new Error(DEVICE_REQUEST_DENIED_MESSAGE, { cause: error })
  }
}

async function takeNativePhoto(): Promise<File[] | null> {
  try {
    await requestSourcePermission('camera')
    const photo = await Camera.getPhoto({
      source: CameraSource.Camera,
      resultType: CameraResultType.Uri,
      quality: 90,
      allowEditing: false,
      correctOrientation: true,
      saveToGallery: false,
    })
    return [await nativePhotoToFile(photo, 0)]
  } catch (error) {
    if (isPickerCancellation(error)) return null
    if (error instanceof Error && error.message === DEVICE_REQUEST_DENIED_MESSAGE) throw error
    throw new Error(DEVICE_REQUEST_DENIED_MESSAGE, { cause: error })
  }
}

/**
 * Capacitor's WebView delegates an input click to the platform document
 * picker. Keeping that implementation here makes the shared app unaware of
 * DOM inputs while leaving room for a native file-picker plugin later.
 */
export function createMobileFilePicker(): RuntimeFileCapabilities {
  return {
    async pick(options = {}) {
      const source = options.source || 'file'
      if (!Capacitor.isNativePlatform()) {
        return domPicker.pick({
          ...options,
          accept: options.accept || (source === 'photos' || source === 'camera' ? 'image/*' : undefined),
        })
      }
      if (source === 'photos') return pickNativePhotos()
      if (source === 'camera') return takeNativePhoto()
      return domPicker.pick(options)
    },
  }
}
