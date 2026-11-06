import type { ReactNode } from 'react'
import { LogOut, Moon, Settings, Sun } from 'lucide-react'
import { Link } from 'react-router-dom'
import AssistantMarker from '@/components/AssistantMarker'
import AssistantPanel from '@/components/AssistantPanel'
import { currentConfig } from '@/api/config'
import favicon from '@/assets/favicon.svg'
import { useAppThemeStore } from '@/stores/appTheme'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import ThemePicker from '@/theme/ThemePicker'

interface Props {
  children: ReactNode
}

/** The frame every view sits in. One component, so the views cannot drift apart. */
export default function AppShell({ children }: Props) {
  const user = useAuthStore((s) => s.user)
  const signOut = useAuthStore((s) => s.signOut)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggle)
  // A theme from the suite brings its own light or dark, so the toggle would fight it.
  const wearing = useAppThemeStore((s) => s.selected !== null)
  const suiteUrl = currentConfig()?.suite_base_url?.replace(/\/+$/, '') || null

  return (
    <div className="flex h-screen flex-col bg-gray-50 dark:bg-gray-900">
      {/* relative z-30: a glass theme blurs the header (assets/glass.css), and a blurred
          element is its own stacking layer, so the theme popup's z-50 only orders it
          inside the header. Without a z-index of its own the whole header paints in
          document order, under the glass cards and pills of the page below it. 30 clears the project view's sticky bar (20) and stays under the dialogs (40). */}
      <header className="relative z-30 shrink-0 border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center gap-3">
          <Link to="/projects" className="flex items-center gap-3">
            <img src={favicon} alt="" aria-hidden="true" className="h-7 w-7" />
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
            {user && <ThemePicker editUrl={suiteUrl ? `${suiteUrl}/themes` : null} />}
            {!wearing && (
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
            )}
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
