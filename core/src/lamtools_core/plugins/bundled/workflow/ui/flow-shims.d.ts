// The plugin is type-checked through core/ui's path map, while the optional
// Vue Flow control packages resolve from the desktop bundle at runtime.
// Keep their public components typed locally without widening the shared UI
// package's module map.
declare module '@vue-flow/controls' {
  export const Controls: any
}

declare module '@vue-flow/minimap' {
  export const MiniMap: any
}
