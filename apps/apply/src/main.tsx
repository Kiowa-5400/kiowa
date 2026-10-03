import React from 'react';
import ReactDOM from 'react-dom/client';
import '@shared/tokens.css';
import './styles.css';
import { App } from './App';
import { AuthProvider } from './auth';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>,
);
