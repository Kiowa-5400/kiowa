import React from 'react';
import ReactDOM from 'react-dom/client';
import '@shared/tokens.css';
import './styles.css';
import { PreviewGate } from '@shared/ui';
import { App } from './App';
import { AuthProvider } from './auth';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <PreviewGate>
      <AuthProvider>
        <App />
      </AuthProvider>
    </PreviewGate>
  </React.StrictMode>,
);
