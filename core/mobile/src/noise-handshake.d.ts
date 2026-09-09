declare module 'noise-handshake' {
  interface KeyPair { publicKey: Uint8Array; secretKey: Uint8Array }
  export default class NoiseHandshake {
    constructor(pattern: string, initiator: boolean, staticKeypair?: KeyPair, options?: { psk?: Uint8Array })
    initialise(prologue: Uint8Array, remoteStatic?: Uint8Array): void
    send(payload?: Uint8Array): Uint8Array
    recv(message: Uint8Array): Uint8Array
    readonly complete: boolean
    readonly tx: Uint8Array
    readonly rx: Uint8Array
    readonly rs: Uint8Array
  }
}

declare module 'noise-handshake/cipher' {
  export default class NoiseCipher {
    constructor(key: Uint8Array)
    encrypt(plaintext: Uint8Array, associatedData?: Uint8Array): Uint8Array
    decrypt(ciphertext: Uint8Array, associatedData?: Uint8Array): Uint8Array
  }
}

declare module 'noise-handshake/dh' {
  export interface NoiseKeyPair { publicKey: Uint8Array; secretKey: Uint8Array }
  export function generateKeyPair(privateKey?: Uint8Array): NoiseKeyPair
}

declare module 'b4a' {
  const b4a: {
    from(value: string | Uint8Array, encoding?: string): Uint8Array
    toString(value: Uint8Array, encoding?: string): string
  }
  export default b4a
}
