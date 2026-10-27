// user:“尽可能的复用能力或维修原有能力”+(主聊天与辅助会话共用附件编码)。
export async function encodeMultipartFile(file: File): Promise<{ body: Uint8Array; contentType: string }> {
  const boundary = `----LamToolsBoundary${globalThis.crypto?.randomUUID?.() || Date.now()}`
  const encoder = new TextEncoder()
  const filename = file.name.replace(/["\r\n]/g, '_')
  const head = encoder.encode(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: ${file.type || 'application/octet-stream'}\r\n\r\n`,
  )
  const content = new Uint8Array(await file.arrayBuffer())
  const tail = encoder.encode(`\r\n--${boundary}--\r\n`)
  const body = new Uint8Array(head.length + content.length + tail.length)
  body.set(head)
  body.set(content, head.length)
  body.set(tail, head.length + content.length)
  return { body, contentType: `multipart/form-data; boundary=${boundary}` }
}
