/** WebAuthn 浏览器侧工具（N006）— 只做编码转换与能力探测。
 *
 * 所有加密学操作都由浏览器/平台 authenticator 完成：这里把 BFF 下发的
 * base64url 参数转成 WebAuthn API 要求的 BufferSource，把
 * navigator.credentials 的结果转回 base64url JSON。不含任何 polyfill；
 * 不支持的平台（非安全上下文 / 无 PublicKeyCredential）诚实报告。
 */

export function webauthnSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.PublicKeyCredential === 'function'
}

export function b64urlToBytes(value: string): Uint8Array {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

export function bytesToB64url(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i])
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** PublicKeyCredentialCreationOptions 的运行时形状（BFF publicKey 载荷）。 */
export type PublicKeyCreationOptionsJson = Record<string, unknown>

/** PublicKeyCredentialRequestOptions 的运行时形状。 */
export type PublicKeyRequestOptionsJson = Record<string, unknown>

/** 把 BFF 的 creation options（base64url 字段）解码为 navigator.credentials.create 参数。 */
export function decodeCreationOptions(publicKey: PublicKeyCreationOptionsJson): PublicKeyCredentialCreationOptions {
  const raw = publicKey as {
    challenge: string
    rp?: { id?: string; name?: string }
    user?: { id: string; name?: string; displayName?: string }
    pubKeyCredParams?: { type: string; alg: number }[]
    timeout?: number
    excludeCredentials?: { id: string; type?: string; transports?: string[] }[]
    authenticatorSelection?: Record<string, unknown>
    attestation?: string
  }
  return {
    challenge: b64urlToBytes(raw.challenge).buffer as ArrayBuffer,
    rp: { id: raw.rp?.id, name: raw.rp?.name ?? 'LumiRSS' },
    user: {
      ...(raw.user ?? {}),
      id: b64urlToBytes(raw.user?.id ?? '').buffer as ArrayBuffer,
    } as PublicKeyCredentialUserEntity,
    pubKeyCredParams: (raw.pubKeyCredParams ?? [{ type: 'public-key', alg: -7 }]).map(
      (param) => ({ type: 'public-key' as const, alg: param.alg }),
    ),
    timeout: raw.timeout,
    excludeCredentials: raw.excludeCredentials?.map((descriptor) => ({
      type: 'public-key' as const,
      id: b64urlToBytes(descriptor.id).buffer as ArrayBuffer,
      transports: descriptor.transports as AuthenticatorTransport[] | undefined,
    })),
    authenticatorSelection: raw.authenticatorSelection as AuthenticatorSelectionCriteria | undefined,
    attestation: (raw.attestation ?? 'none') as AttestationConveyancePreference,
  }
}

/** 把 BFF 的 request options 解码为 navigator.credentials.get 参数。 */
export function decodeRequestOptions(publicKey: PublicKeyRequestOptionsJson): PublicKeyCredentialRequestOptions {
  const raw = publicKey as {
    challenge: string
    rpId?: string
    timeout?: number
    allowCredentials?: { id: string; type?: string; transports?: string[] }[]
    userVerification?: string
  }
  return {
    challenge: b64urlToBytes(raw.challenge).buffer as ArrayBuffer,
    rpId: raw.rpId,
    timeout: raw.timeout,
    allowCredentials: raw.allowCredentials?.map((descriptor) => ({
      type: 'public-key' as const,
      id: b64urlToBytes(descriptor.id).buffer as ArrayBuffer,
      transports: descriptor.transports as AuthenticatorTransport[] | undefined,
    })),
    userVerification: (raw.userVerification ?? 'preferred') as UserVerificationRequirement,
  }
}

/** RegistrationResponse → BFF JSON（base64url 序列化）。 */
export function encodeRegistrationResponse(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: bytesToB64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bytesToB64url(response.clientDataJSON),
      attestationObject: bytesToB64url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
  }
}

/** AuthenticationResponse → BFF JSON（base64url 序列化）。 */
export function encodeAssertionResponse(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response as AuthenticatorAssertionResponse
  return {
    id: credential.id,
    rawId: bytesToB64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bytesToB64url(response.clientDataJSON),
      authenticatorData: bytesToB64url(response.authenticatorData),
      signature: bytesToB64url(response.signature),
      userHandle: response.userHandle ? bytesToB64url(response.userHandle) : null,
    },
  }
}
