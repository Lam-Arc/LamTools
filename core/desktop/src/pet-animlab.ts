/**
 * 方块人动画实验台入口：普通页面，不依赖透明覆盖层与 Tauri 也能跑。
 *
 * user:"把这个桌宠给我拆开 拆成 ping/几何判定框与平台的地图与寻路模型/桌宠动画"+
 * "现在做方块人的动画，用独立的 HTML 给我展示出来，然后底下要可以控制动作组"+
 * (本入口只装"方块人动画"这一块：骨架 + blockyPose + 动作组控制；
 *  不 import PetSurface/bridge/usePetRuntime/引擎世界，三块互不一起调试。)
 */
import { createApp } from 'vue'
import PetAnimLab from '@/pet/ui/PetAnimLab.vue'

const host = document.getElementById('animlab')
if (host) {
  createApp(PetAnimLab).mount(host)
}
