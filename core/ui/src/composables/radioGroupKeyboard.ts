// user:“确保视觉、功能和交互不退化”+(单选组用方向键与首尾键切换，保留每种控件自己的视觉样式和点击行为)。
export function onRadioGroupKeydown(event: KeyboardEvent): void {
  onGroupKeydown(event, 'radio')
}

// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(标签组复用方向键和首尾键导航，不改变标签语义)。
export function onTabGroupKeydown(event: KeyboardEvent): void {
  onGroupKeydown(event, 'tab')
}

// user:“确保视觉、功能和交互不退化”+(有草稿保护的标签方向键只移动焦点，交由原有激活操作判断)。
export function onManualTabGroupKeydown(event: KeyboardEvent): void {
  onGroupKeydown(event, 'tab', false)
}

function onGroupKeydown(event: KeyboardEvent, role: 'radio' | 'tab', activate = true): void {
  const group = event.currentTarget
  const target = event.target
  if (!(group instanceof HTMLElement) || !(target instanceof Element)) return
  const current = target.closest<HTMLButtonElement>(`button[role="${role}"]`)
  if (!current || !group.contains(current)) return
  // user:“确保视觉、功能和交互不退化”+(标签内的独立操作保留自己的键盘行为)。
  const innerControl = target.closest('[role="button"], a, input, select, textarea, button')
  if (innerControl && innerControl !== current && current.contains(innerControl)) return
  const radios = Array.from(group.querySelectorAll<HTMLButtonElement>(`button[role="${role}"]:not(:disabled)`))
  const index = radios.indexOf(current)
  if (index < 0 || !radios.length) return
  let next: number
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % radios.length
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + radios.length - 1) % radios.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = radios.length - 1
  else return
  event.preventDefault()
  const button = radios[next]
  button.focus()
  if (activate) button.click()
}
