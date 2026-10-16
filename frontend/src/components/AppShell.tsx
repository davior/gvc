import type { ReactNode } from 'react'
import { LogOut, Moon, Settings, Sun } from 'lucide-react'
import { Link } from 'react-router-dom'
import AssistantMarker from '@/components/AssistantMarker'
import AssistantPanel from '@/components/AssistantPanel'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

interface Props {
  children: ReactNode
}

/** The frame every view sits in. One component, so the views cannot drift apart. */
export default function AppShell({ children }: Props) {
  const user = useAuthStore((s) => s.user)
  const signOut = useAuthStore((s) => s.signOut)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggle)

  return (
    <div className="flex h-screen flex-col bg-gray-50 dark:bg-gray-900">
      <header className="shrink-0 border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center gap-3">
          <Link to="/projects" className="flex items-center gap-3">
            <span className="text-xl" aria-hidden="true">
              🦎
            </span>
            <h1 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              Gecko Video Creator
            </h1>
          </Link>

          <div className="ml-auto flex items-center gap-3">
            {user && <AssistantMarker />}
            <Link
              to="/settings"
              className="btn btn-ghost p-2"
              aria-label="Settings"
              title="Settings"
            >
              <Settings className="h-4 w-4" />
            </Link>
            <button
              type="button"
              onClick={toggleTheme}
              className="btn btn-ghost p-2"
              aria-label={
                theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
              }
            >
              {theme === 'dark' ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Moon className="h-4 w-4" />
              )}
            </button>
            {user && (
              <>
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  {user.username}
                </span>
                <button
                  type="button"
                  onClick={signOut}
                  className="btn btn-ghost p-2"
                  aria-label="Sign out"
                  title="Sign out"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* The assistant sits beside every page, so it can follow you around the app. */}
      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
        {user && <AssistantPanel />}
      </div>
    </div>
  )
}
