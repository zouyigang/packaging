import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#176bff',
          borderRadius: 8,
          colorText: '#172033',
          colorTextSecondary: '#667085',
          colorBorder: '#dce3ec',
          boxShadowSecondary: '0 10px 28px rgba(16, 24, 40, 0.10)',
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
