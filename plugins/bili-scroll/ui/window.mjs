// user:“该调的模块就是该写的东西”+(独立窗口不依赖主窗口的 JavaScript 全局变量)。
import { mount } from './page.mjs';
const signal=new AbortController();
async function rpc(method,params={}) {
 const response=await fetch('/api/core/plugin-system/bili-scroll/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({method,params}),signal:signal.signal});
 const result=await response.json();
 if(!response.ok||result.status==='error'||result.status==='blocked')throw new Error(result.payload?.error||result.detail||'操作失败');
 if(result.status==='approval_required') {
  const approved=window.confirm(result.payload.approval.impact);
  return rpc('plugin.system.operation.respond',{id:result.payload.approval.id,decision:approved?'approve':'deny'});
 }
 return result.payload||{};
}
mount(document.querySelector('#root'),{rpc,signal:signal.signal,visible:true,onVisibilityChange:()=>()=>{}});
window.addEventListener('beforeunload',()=>signal.abort(),{once:true});
