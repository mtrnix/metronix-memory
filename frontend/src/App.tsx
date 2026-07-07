import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { isAuthenticated, LoginPage } from '@/shared';
import Layout from './components/layout/Layout';
import SourcesPage from './components/sources/SourcesPage';
import HealthPage from './components/health/HealthPage';
import MemoryInspectorPage from './components/memory/MemoryInspectorPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

export default function App() {
  const [authed, setAuthed] = useState(isAuthenticated());

  if (!authed) {
    return <LoginPage onSuccess={() => setAuthed(true)} />;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/sources" replace />} />
            <Route path="sources" element={<SourcesPage />} />
            <Route path="memory" element={<MemoryInspectorPage />} />
            <Route path="health" element={<HealthPage />} />
            <Route path="*" element={<Navigate to="/sources" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" theme="dark" />
    </QueryClientProvider>
  );
}
