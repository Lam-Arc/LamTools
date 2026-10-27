// user:“如图，我不清楚这是不是你写出来的界面的设计的样子”+(按实际主界面组件与全局样式挂载画布)。
import { createApp, defineComponent, h } from 'vue'
import CoreSplitPluginPage from '../../../src/components/CoreSplitPluginPage.vue'
import { pluginPageKey } from '../../../src/plugins/pages'
import '../../../src/styles/variables.css'
import '../../../src/styles/base.css'
import '../../../src/styles/layout.css'
import '../../../src/styles/theme-editor.css'
import '../../../src/styles/library-surface.css'
const page={plugin:'excalidraw',id:'canvas',title:'Excalidraw',version:'0.1.14-dev',entry_url:'/api/core/plugin-system/excalidraw/assets/ui/page.mjs'}
const rpc=async(method:string)=>method==='plugin.system.ui'?{pages:[page],styles:[],scripts:[],regions:[]}:{plugins:[{name:'excalidraw',enabled:true}]}
createApp(defineComponent({setup(){return ()=>h('main',{class:'workspace-main workspace-main--no-composer',style:'--main-left:94px;--main-right:10px;--main-x-padding:18px'},[
 h('header',{class:'thread-header full-area-header'},'Excalidraw'),
 h('div',{class:'workspace-main-default'},[h(CoreSplitPluginPage,{tab:{id:'main',kind:'plugin',resource:pluginPageKey('excalidraw','canvas'),title:'Excalidraw',root:'E:/LamTools'},visible:true,workRoot:'E:/LamTools',requestRpc:rpc})])
])}})).mount('#app')
