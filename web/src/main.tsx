import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <main>
      <p>AgentTinker</p>
      <h1>运行检查台</h1>
      <p>共享运行协议已接入，历史与步骤检查界面正在实现。</p>
    </main>
  </StrictMode>,
);
