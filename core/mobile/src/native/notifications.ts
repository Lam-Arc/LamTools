export type MobileNotificationKind = 'approval' | 'question' | 'connection'

export interface MobileNotification {
  kind: MobileNotificationKind
  title: string
  body: string
  eventId?: string
}

/** Native push integration point. Web/dev keeps notifications in-app. */
export async function notifyMobile(_notification: MobileNotification): Promise<void> {
  // APNs/FCM adapters are added in the Capacitor native projects.
}

export interface PushRegistration {
  token: string
  platform: 'ios' | 'android'
}

/** Registers the native APNs/FCM adapter. The token is returned to the caller
 * for the relay registry and is never placed in ordinary localStorage. */
export async function registerPushNotifications(
  onNotification?: (notification: PushNotificationSchema) => void,
): Promise<PushRegistration | null> {
  if (!Capacitor.isNativePlatform()) return null
  const permission = await PushNotifications.checkPermissions()
  const granted = permission.receive === 'granted'
    ? permission
    : await PushNotifications.requestPermissions()
  if (granted.receive !== 'granted') return null
  return await new Promise<PushRegistration>((resolve, reject) => {
    let settled = false
    void PushNotifications.addListener('registration', ({ value }) => {
      if (settled) return
      settled = true
      resolve({ token: value, platform: Capacitor.getPlatform() === 'ios' ? 'ios' : 'android' })
    })
    void PushNotifications.addListener('registrationError', (error) => {
      if (settled) return
      settled = true
      reject(new Error(error.error || '推送注册失败'))
    })
    if (onNotification) void PushNotifications.addListener('pushNotificationReceived', onNotification)
    void PushNotifications.register()
  })
}
import { Capacitor } from '@capacitor/core'
import { PushNotifications, type PushNotificationSchema } from '@capacitor/push-notifications'
