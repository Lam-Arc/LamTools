/**
 * 把一张询问卡拍成文本：分组、题目、题型、选项与已填答案。
 *
 * user:“询问卡右上角加一个复制图标按钮”+(复制的是这张卡现在的样子——没答的和答过的
 * 都在里面：答过的那几行带「回答」，没答的只留题目与选项。)
 */
export interface QuestionGroupCopyEntry {
  /** 分组标题（必答 / 可选）。 */
  section: string
  /** 分组说明，例如「填写后才能继续」。 */
  sectionHint?: string
  title: string
  /** 题型标签：单选 / 多选 / 自由输入。 */
  typeLabel?: string
  description?: string
  options?: string[]
  /** 已填的答案；没填就留空，不输出「回答」这一行。 */
  answer?: string
}

export function questionGroupCopyText(entries: QuestionGroupCopyEntry[]): string {
  const lines: string[] = []
  let section = ''
  for (const entry of entries) {
    const title = String(entry.title || '').trim()
    if (!title) continue
    if (entry.section !== section) {
      if (lines.length > 0) lines.push('')
      section = entry.section
      const hint = String(entry.sectionHint || '').trim()
      lines.push(hint ? `${section} · ${hint}` : section)
    }
    lines.push(`- ${title}${entry.typeLabel ? `（${entry.typeLabel}）` : ''}`)
    const description = String(entry.description || '').trim()
    if (description) lines.push(`  说明：${description}`)
    const options = (entry.options || []).map(option => String(option || '').trim()).filter(Boolean)
    if (options.length > 0) lines.push(`  选项：${options.join('、')}`)
    const answer = String(entry.answer || '').trim()
    if (answer) {
      // 自由输入可以是多行：续行缩进两格，粘出来仍然是一个整体。
      const [first, ...rest] = answer.split(/\r?\n/)
      lines.push(`  回答：${first}`)
      for (const line of rest) lines.push(`    ${line}`)
    }
  }
  return lines.join('\n')
}
