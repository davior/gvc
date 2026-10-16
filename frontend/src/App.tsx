import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from '@/components/AppShell'
import RequireAuth from '@/components/RequireAuth'
import ProjectListView from '@/views/ProjectListView'
import ProjectView from '@/views/ProjectView'
import SettingsView from '@/views/SettingsView'
import { loadConfig } from '@/api/config'
import { setUnauthorizedHandler } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap)

  // One identity check on load. Everything below the shell can assume it has run.
  useEffect(() => {
    void bootstrap()
    // Early, so the sign-in address is in hand before anybody clicks. Memoised.
    void loadConfig().catch(() => {
      // Not fatal: `RequireAuth` already reports an unreachable backend.
    })
  }, [bootstrap])

  // Set here rather than in `api/client.ts`, which cannot import the auth store
  // without an import cycle (store → api/auth → client).
  useEffect(() => {
    setUnauthorizedHandler(() => {
      // Only for a session that *was* good; an anonymous visitor's 401 is what
      // RequireAuth's sign-in button is for.
      const auth = useAuthStore.getState()
      if (auth.status !== 'authenticated') return false
      auth.signOut()
      return true
    })
  }, [])

  const page = (view: JSX.Element) => (
    <RequireAuth>
      <AppShell>{view}</AppShell>
    </RequireAuth>
  )

  return (
    <Routes>
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={page(<ProjectListView />)} />
      <Route path="/p/:id" element={page(<ProjectView />)} />
      <Route path="/settings" element={page(<SettingsView />)} />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}
