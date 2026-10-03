import React from 'react';
import ReactDOM from 'react-dom/client';
import '@shared/tokens.css';
import './styles.css';
import { App } from './App';
import { SiteProvider } from './site';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <SiteProvider>
      <App />
    </SiteProvider>
  </React.StrictMode>,
);
