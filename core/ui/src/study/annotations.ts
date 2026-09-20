import { ref } from 'vue'
import type { StudyMark, TextAction } from './types'
export const marks = ref<StudyMark[]>([])
export const selectionEvents = new EventTarget()
export function showMark(mark: StudyMark, action: TextAction) {
  selectionEvents.dispatchEvent(new CustomEvent('open', { detail: { mark, action } }))
}
export function jumpMark(mark: StudyMark) {
  selectionEvents.dispatchEvent(new CustomEvent('jump', { detail: mark }))
}
export function deleteMark(mark: StudyMark) {
  selectionEvents.dispatchEvent(new CustomEvent('delete', { detail: mark }))
}
