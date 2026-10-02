/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_APPLY_APP_URL?: string;
  readonly VITE_BOARD_APP_URL?: string;
}

declare module '*.avif' {
  const src: string;
  export default src;
}
