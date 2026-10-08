/* 办公段的右栏：真实资料库，按 780 宽渲染（文件墙：成品与过程产物都在这里）。 */

import { type StageScene } from '../src/timeline'
import { officeData, useLibrary } from './_film-office-parts'

export default {
  id: 'film-lib-files',
  duration: 4,

  frame(t) {
    useLibrary(t, '资料')
    return { rect: { x: 0, y: 0, w: 780, h: 888, radius: 0 }, overlay: '', caption: { title: '', hint: '' } }
  },

  data(t, revision) {
    return officeData(t, revision, 'film-lib-files')
  },
} satisfies StageScene
