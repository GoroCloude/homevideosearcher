import { NavLink, Outlet } from 'react-router-dom';
import clsx from 'clsx';
import ToastContainer from './Toast';

const NAV_ITEMS = [
  { to: '/',         label: 'Search',   icon: '🔍' },
  { to: '/videos',   label: 'Videos',   icon: '🎬' },
  { to: '/people',   label: 'People',   icon: '👤' },
  { to: '/clusters', label: 'Clusters', icon: '👥' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
] as const;

export default function Layout() {
  return (
    <div className="flex h-screen bg-gray-50">

      {/* Desktop sidebar — hidden on mobile */}
      <nav className="hidden sm:flex flex-col w-48 bg-white border-r border-gray-200 py-4 shrink-0">
        <div className="px-4 mb-6">
          <span className="text-sm font-semibold text-gray-500 uppercase tracking-wider">
            HomeVideoSearcher
          </span>
        </div>
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-4 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-blue-50 text-blue-700 border-r-2 border-blue-600'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
              )
            }
          >
            <span className="text-lg leading-none">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto pb-16 sm:pb-0">
        <Outlet />
      </main>

      {/* Mobile bottom tab bar — visible only on mobile */}
      <nav className="sm:hidden fixed bottom-0 inset-x-0 bg-white border-t border-gray-200 flex z-30">
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex-1 flex flex-col items-center justify-center py-2 text-xs gap-1 transition-colors',
                isActive ? 'text-blue-600' : 'text-gray-500 hover:text-gray-700',
              )
            }
          >
            <span className="text-xl leading-none">{item.icon}</span>
            <span className="sr-only">{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <ToastContainer />

    </div>
  );
}
