// user:“该修就修，不用停下”+(文件树通过插件声明打开对应文件，保持项目与文件的独立身份)。
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createPluginPageInstance, findPluginFilePage, parsePluginPageKey, pluginPageKey } from '../src/plugins/pages'
import { useSplitWorkspace } from '../src/split/useSplitWorkspace'
import { restoreSplitState } from '../src/split/layout'
afterEach(() => {localStorage.clear();vi.restoreAllMocks()})
const page={plugin:'excalidraw',id:'canvas',title:'Excalidraw',entry_url:'/api/core/plugin-system/excalidraw/assets/ui/page.mjs',file_extensions:['.excalidraw.md','.excalidraw']}
it('selects the longest declared extension and avoids ambiguous associations', () => {
  const md={...page,plugin:'markdown',id:'md',file_extensions:['.md']}
  expect(findPluginFilePage([md,page],'E:/work/demo.EXCALIDRAW.MD')).toEqual(page)
  expect(findPluginFilePage([page, {...page,plugin:'other'}],'E:/work/demo.excalidraw')).toBeNull()
  expect(findPluginFilePage([page],'E:/work/readme.md')).toBeNull()
})
it('persists distinct file-bound plugin tabs and gives the original path to the page', async () => {
  let controller: ReturnType<typeof useSplitWorkspace>
  const wrapper=mount(defineComponent({setup(){controller=useSplitWorkspace(ref('file-association'),ref('E:/work'),ref('project'));return ()=>h('div')}}))
  try {
    controller!.openPluginPage(page,undefined,{workRoot:'E:/work',projectId:'project',filePath:'E:/work/a.excalidraw.md'})
    controller!.openPluginPage(page,undefined,{workRoot:'E:/work',projectId:'project',filePath:'E:/work/b.excalidraw.md'})
    const restored=restoreSplitState(JSON.stringify(controller!.state));const tabs=Object.values(restored.panes).flatMap(p=>p.tabs)
    expect(tabs).toHaveLength(2)
    expect(parsePluginPageKey(tabs[0].resource)).toEqual(['excalidraw','canvas','E:/work/a.excalidraw.md'])
    expect(pluginPageKey('excalidraw','canvas')).toBe(JSON.stringify(['excalidraw','canvas']))
    let path=''
    const instance=createPluginPageInstance(document.createElement('div'),page,{instanceId:'a',workRoot:'E:/work',filePath:'E:/work/a.excalidraw.md'},vi.fn(),{loadModule:async()=>({mount(_root,context){path=context.filePath || ''}})})
    await instance.ready;expect(path).toBe('E:/work/a.excalidraw.md');await instance.dispose()
  } finally {wrapper.unmount()}
})

it('routes the file tree selection to its declared plugin with the correct project', async () => {
  const { setPluginPageEntries } = await import('../src/plugins/contributions')
  const { default: CoreSplitContent } = await import('../src/components/CoreSplitContent.vue')
  const { flushPromises } = await import('@vue/test-utils')
  setPluginPageEntries([page])
  let controller: ReturnType<typeof useSplitWorkspace>
  const wrapper=mount(defineComponent({setup(){
    controller=useSplitWorkspace(ref('open-association'),ref('E:/work'),ref('project'))
    controller.add('files','E:/work','Files',undefined,undefined,'E:/work','project')
    return ()=>{const entry=controller.tabs.value.find(x=>x.tab.kind==='files')!;return h(CoreSplitContent,{tab:entry.tab,pane:entry.pane,visible:true,controller,workRoot:'E:/work',documents:{} as never,bindings:{},transport:{} as never,messages:[],activeSessionId:'',memberStatuses:{},memberStatusRecords:{},durableRecords:{},memberWaitKnown:false,runningMemberNames:[],mainRunning:false})}
  }}),{global:{stubs:{CoreSplitFileTree:defineComponent({name:'CoreSplitFileTree',emits:['open'],setup(_,{emit}){return ()=>h('button',{onClick:()=>emit('open','E:/work/画图.excalidraw.md')},'open')}})}}})
  try {
    await wrapper.get('button').trigger('click');await flushPromises()
    const tab=controller!.tabs.value.find(x=>x.tab.kind==='plugin')?.tab
    expect(tab?.resource).toBe(pluginPageKey('excalidraw','canvas','E:/work/画图.excalidraw.md'))
    expect(tab?.root).toBe('E:/work');expect(tab?.projectId).toBe('project')
  } finally {wrapper.unmount();setPluginPageEntries([])}
})

it('loads plugin declarations before routing a file selected at startup', async () => {
  const { setPluginPageEntries } = await import('../src/plugins/contributions')
  const { default: CoreSplitContent } = await import('../src/components/CoreSplitContent.vue')
  const { flushPromises } = await import('@vue/test-utils')
  setPluginPageEntries([])
  const rpc=vi.fn(async (method:string)=>method==='plugin.system.ui'?{pages:[page],styles:[],scripts:[],regions:[]}:{plugins:[{name:'excalidraw',enabled:true}]})
  let controller:ReturnType<typeof useSplitWorkspace>
  const wrapper=mount(defineComponent({setup(){
    controller=useSplitWorkspace(ref('load-association'),ref('E:/work'),ref('project'))
    controller.add('files','E:/work','Files',undefined,undefined,'E:/work','project')
    return ()=>{const entry=controller.tabs.value.find(x=>x.tab.kind==='files')!;return h(CoreSplitContent,{tab:entry.tab,pane:entry.pane,visible:true,controller,workRoot:'E:/work',documents:{} as never,bindings:{plugins:{requestRpc:rpc}},transport:{} as never,messages:[],activeSessionId:'',memberStatuses:{},memberStatusRecords:{},durableRecords:{},memberWaitKnown:false,runningMemberNames:[],mainRunning:false})}
  }}),{global:{stubs:{CoreSplitFileTree:defineComponent({name:'CoreSplitFileTree',emits:['open'],setup(_,{emit}){return ()=>h('button',{onClick:()=>emit('open','E:/work/a.excalidraw')},'open')}})}}})
  try {
    await wrapper.get('button').trigger('click');await flushPromises()
    expect(rpc).toHaveBeenCalledWith('plugin.system.ui',{})
    expect(controller!.tabs.value.find(x=>x.tab.kind==='plugin')?.tab.resource).toBe(pluginPageKey('excalidraw','canvas','E:/work/a.excalidraw'))
  } finally {wrapper.unmount();setPluginPageEntries([])}
})

it('plugin file navigation is scoped to its instance and closes with it', async () => {
  const opened:string[]=[];let navigate:(path:string)=>void=()=>{}
  const instance=createPluginPageInstance(document.createElement('div'),page,{instanceId:'a',workRoot:'E:/work'},vi.fn(),{
    openFile:path=>opened.push(path),loadModule:async()=>({mount(_root,context){navigate=context.openFile}}),
  })
  await instance.ready;navigate('E:/work/note.md');await instance.dispose();navigate('E:/work/after.md')
  expect(opened).toEqual(['E:/work/note.md'])
})

it('file navigation retains the project captured by the mounted page', async () => {
  const pageModules=await import('../src/plugins/pages')
  const {setPluginPageEntries}=await import('../src/plugins/contributions')
  const {default:CoreSplitPluginPage}=await import('../src/components/CoreSplitPluginPage.vue')
  const {flushPromises}=await import('@vue/test-utils')
  let context: any
  vi.spyOn(pageModules,'loadPluginPageModule').mockResolvedValue({mount(_root,ctx){context=ctx}})
  setPluginPageEntries([page])
  const rpc=vi.fn(async(method:string)=>method==='plugin.system.ui'?{pages:[page]}:{plugins:[{name:'excalidraw',enabled:true}]})
  const tab={id:'one',kind:'plugin' as const,resource:pluginPageKey('excalidraw','canvas'),title:'Excalidraw',root:'E:/first',projectId:'first'}
  const wrapper=mount(CoreSplitPluginPage,{props:{tab,visible:true,workRoot:'E:/first',requestRpc:rpc}})
  try{
    await flushPromises();expect(context).toBeTruthy()
    await wrapper.setProps({tab:{...tab,root:'E:/second',projectId:'second'},workRoot:'E:/second'})
    context.openFile('E:/first/note.md')
    expect(wrapper.emitted('open-file')?.[0]).toEqual(['E:/first/note.md',{workRoot:'E:/first',projectId:'first',sessionId:undefined}])
  }finally{wrapper.unmount();setPluginPageEntries([])}
})
