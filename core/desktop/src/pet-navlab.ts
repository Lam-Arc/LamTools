/**
 * 地图与寻路实验台入口：普通页面，不依赖透明覆盖层与 Tauri 也能跑。
 *
 * user:"把这个桌宠给我拆开 拆成 ping/几何判定框与平台的地图与寻路模型/桌宠动画"+
 * "还是那件事儿 不要让他一起调试"+
 * (本入口只装"几何判定框与平台的地图与寻路模型"这一块；Ping 与桌宠动画
 *  各自单独出界面。不 import PetSurface/bridge/usePetRuntime，互相不耦合。)
 */
import { createApp } from 'vue'
import PetNavLab from '@/pet/ui/PetNavLab.vue'

const host = document.getElementById('navlab')
if (host) {
  createApp(PetNavLab).mount(host)
}
