/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

// The bundled workflow UI lives with the backend plugin source and is aliased
// to that entry by the Vite app configs. Keep the library typecheck boundary
// local to core/ui; the plugin UI has its own project typecheck.
declare module '@lamtools/bundled-workflow-ui' {
  const entry: import('vue').Component;
  export default entry;
}
