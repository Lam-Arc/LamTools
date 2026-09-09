export { PairingClient } from './PairingClient'
export { loadOrCreateAccountDeviceIdentity, loadOrCreateDeviceIdentity, type DeviceIdentity } from './DeviceIdentity'
export {
  forgetTrustedDevice,
  listTrustedDevices,
  saveTrustedDevice,
  configureTrustedDeviceMetadataStorage,
  MemoryTrustedDeviceMetadataStorage,
  trustedDeviceStores,
  type TrustedDeviceCredential,
  type TrustedDeviceMetadata,
  type TrustedDeviceMetadataStorage,
  type TrustedDeviceStores,
  type TrustedDevice,
} from './TrustedDevices'
