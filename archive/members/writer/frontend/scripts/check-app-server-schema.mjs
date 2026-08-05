import { readFile } from 'node:fs/promises'

const schemaPath = new URL('../src/appServer/protocol.schema.json', import.meta.url)
const protocolPath = new URL('../src/appServer/protocol.ts', import.meta.url)

const schema = JSON.parse(await readFile(schemaPath, 'utf8'))
const protocolTs = await readFile(protocolPath, 'utf8')

const envelope = schema.models?.WriterAppEventEnvelope
if (!envelope?.properties || !Array.isArray(envelope.required)) {
  throw new Error('WriterAppEventEnvelope schema is missing properties/required')
}

const eventInterface = interfaceBody(protocolTs, 'WriterAppEvent')
const missingFields = Object.keys(envelope.properties).filter((field) => !new RegExp(`\\b${field}\\??\\s*:`).test(eventInterface))
if (missingFields.length) {
  throw new Error(`src/appServer/protocol.ts WriterAppEvent is missing backend schema fields: ${missingFields.join(', ')}`)
}

const protocolVersion = envelope.properties.protocol_version?.const
if (protocolVersion && !protocolTs.includes(`'${protocolVersion}'`)) {
  throw new Error(`src/appServer/protocol.ts is missing protocol version ${protocolVersion}`)
}

for (const field of envelope.required) {
  if (new RegExp(`\\b${field}\\?\\s*:`).test(eventInterface)) {
    throw new Error(`src/appServer/protocol.ts marks required backend field as optional: ${field}`)
  }
}

console.log(`app-server schema check passed (${Object.keys(envelope.properties).length} event fields)`)

function interfaceBody(source, name) {
  const start = source.indexOf(`interface ${name}`)
  if (start === -1) throw new Error(`Missing interface ${name}`)
  const open = source.indexOf('{', start)
  if (open === -1) throw new Error(`Missing body for interface ${name}`)
  let depth = 0
  for (let index = open; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(open + 1, index)
    }
  }
  throw new Error(`Unclosed interface ${name}`)
}
