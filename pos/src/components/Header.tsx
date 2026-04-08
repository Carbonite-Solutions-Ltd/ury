import { useState, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Command,
  User,
  ChevronDown,
  Monitor,
  LogOut,
  RefreshCw,
  MapPin,
} from 'lucide-react';
import { Button, Input } from './ui';
import { useRootStore } from '../store/root-store';
import { usePOSStore } from '../store/pos-store';
import type { RootState } from '../store/root-store';
import { logout } from '../lib/auth-api';
import { showToast } from './ui/toast';
import { clearSavedTerminal } from '../lib/terminal-api';

const Header = () => {
  const [showUserMenu, setShowUserMenu] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const user = useRootStore((state: RootState) => state.user);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const location = useLocation();
  const {
    searchQuery,
    setSearchQuery,
    terminalName,
    terminalBranch,
    terminalPosProfile,
    terminalDescription,
    selectedRoom,
  } = usePOSStore();
  const { orderSearchQuery, setOrderSearchQuery } = useRootStore();
  const [orderSearchInput, setOrderSearchInput] = useState(orderSearchQuery);

  // Determine placeholder and handlers based on route
  let searchPlaceholder = 'Search orders, menu items, or customers...';
  let searchValue: string | undefined = undefined;
  let searchOnChange: ((e: React.ChangeEvent<HTMLInputElement>) => void) | undefined = undefined;
  if (location.pathname === '/orders') {
    searchPlaceholder = 'Search Orders';
    searchValue = orderSearchInput;
    searchOnChange = (e) => setOrderSearchInput(e.target.value);
  } else if (location.pathname === '/') {
    searchPlaceholder = 'Search Menu';
    searchValue = searchQuery;
    searchOnChange = (e) => setSearchQuery(e.target.value);
  }

  // Debounce order search
  useEffect(() => {
    if (location.pathname !== '/orders') return;
    const handler = setTimeout(() => {
      setOrderSearchQuery(orderSearchInput);
    }, 300);
    return () => clearTimeout(handler);
  }, [orderSearchInput, setOrderSearchQuery, location.pathname]);

  // Keep input in sync with store (if cleared elsewhere)
  useEffect(() => {
    if (location.pathname === '/orders') {
      setOrderSearchInput(orderSearchQuery);
    }
  }, [location.pathname, orderSearchQuery]);

  // Handle clicks outside of menus
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setShowUserMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleUserMenuToggle = () => {
    setShowUserMenu(!showUserMenu);
  };

  const handleLogout = async () => {
    try {
      await logout();
      window.location.href = '/login?redirect-to=%2Fpos';
    } catch (error) {
      showToast.error('Failed to logout. Please try again.');
    }
  };

  const handleClearCache = () => {
    // Preserve terminal registration, clear everything else
    const savedTerminal = localStorage.getItem('ury_pos_terminal');
    localStorage.clear();
    if (savedTerminal) {
      localStorage.setItem('ury_pos_terminal', savedTerminal);
    }
    sessionStorage.clear();
    window.location.reload();
  };

  const handleChangeTerminal = () => {
    clearSavedTerminal();
    sessionStorage.clear();
    window.location.reload();
  };


  return (
    <header className="bg-white border-b border-gray-200">
      <div className="flex items-center justify-between h-16 px-6">
        {/* Logo */}
        <div className="flex items-center">
        <Link to="/" className="flex items-center space-x-3">
            <img 
              src="/assets/ury/pos/ury_pos.png" 
              alt="URY POS" 
              className="h-10 w-auto"
            />
          </Link>
          {terminalName && (
            // "terminal · branch · profile" chip so the cashier can see
            // at a glance exactly what context they're ringing in.
            // See CLAUDE.md "Fixes log" 2026-04-08.
            <span
              className="ml-3 inline-flex items-center gap-1.5 text-xs font-medium text-gray-700 bg-gray-100 border border-gray-200 rounded-md px-2.5 py-1"
              title={terminalDescription || undefined}
            >
              <Monitor className="w-3 h-3 text-gray-500" />
              <span>{terminalName}</span>
              {terminalBranch && (
                <>
                  <span className="text-gray-400">·</span>
                  <span>{terminalBranch}</span>
                </>
              )}
              {terminalPosProfile && (
                <>
                  <span className="text-gray-400">·</span>
                  <span>{terminalPosProfile}</span>
                </>
              )}
            </span>
          )}
        </div>

        {/* Search Bar */}
        <div className="px-4 py-2 flex-1 flex items-center max-w-2xl mx-8  bg-gray-50 hover:bg-gray-100 border border-input rounded-md">
            <Input
              ref={searchInputRef}
              placeholder={searchPlaceholder}
              className="h-fit p-0 w-full bg-transparent border-0 focus:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
              value={searchValue}
              onChange={searchOnChange}
            />
            <div className="flex items-center gap-2 text-gray-400">
              <Command className="w-4 h-4" />
              <span>K</span>
            </div>
        </div>

        {/* Right side actions */}
        <div className="flex items-center space-x-4">
          {/* User menu */}
          <div className="relative" ref={userMenuRef}>
            <Button
              onClick={handleUserMenuToggle}
              variant="ghost"
              className="flex items-center space-x-2 text-gray-600 hover:text-gray-900"
            >
              <div className="w-8 h-8 bg-primary-500 rounded-full flex items-center justify-center">
                <User className="w-4 h-4 text-white" />
              </div>
              <span className="text-sm font-medium">{user?.full_name || 'User'}</span>
              <ChevronDown className="w-4 h-4" />
            </Button>

            {/* User dropdown */}
            {showUserMenu && (
              <div className="absolute right-0 mt-2 w-56 bg-white rounded-lg shadow-lg border border-gray-200 z-50">
                <div className="p-4 border-b border-gray-200">
                  <p className="text-sm font-medium text-gray-900">{user?.full_name || 'User'}</p>
                  <p className="text-sm text-gray-500">{user?.name || ''}</p>
                  {terminalName && (
                    <div className="flex items-center gap-1.5 mt-2 text-xs text-blue-600 bg-blue-50 rounded-md px-2 py-1">
                      <Monitor className="w-3 h-3" />
                      <span className="font-medium">{terminalName}</span>
                      {terminalBranch && (
                        <span className="text-blue-400">· {terminalBranch}</span>
                      )}
                    </div>
                  )}
                  {terminalPosProfile && (
                    <div className="flex items-center gap-1.5 mt-1 text-xs text-gray-500">
                      <span className="w-3 h-3 inline-block" />
                      <span>POS Profile: {terminalPosProfile}</span>
                    </div>
                  )}
                  {selectedRoom && (
                    <div className="flex items-center gap-1.5 mt-1 text-xs text-gray-500">
                      <MapPin className="w-3 h-3" />
                      <span>{selectedRoom}</span>
                    </div>
                  )}
                  {terminalDescription && (
                    <div className="mt-2 text-xs text-gray-400 italic">
                      {terminalDescription}
                    </div>
                  )}
                </div>
                <div className="py-2">
                  <Button
                    variant="ghost"
                    className="flex justify-start items-center w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors"
                    onClick={handleChangeTerminal}
                  >
                    <MapPin className="w-4 h-4 mr-3" />
                    Change Terminal
                  </Button>
                  <Button
                    variant="ghost"
                    className="flex justify-start items-center w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors"
                    onClick={() => window.location.href = '/app'}
                  >
                    <Monitor className="w-4 h-4 mr-3" />
                    Switch To Desk
                  </Button>
                  <Button
                    variant="ghost"
                    className="flex justify-start items-center w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors"
                    onClick={handleClearCache}
                  >
                    <RefreshCw className="w-4 h-4 mr-3" />
                    Clear Cache
                  </Button>
                  <Button
                    variant="ghost"
                    className="flex justify-start items-center w-full px-4 py-2 text-sm text-red-600 hover:bg-red-50 hover:text-red-700 transition-colors"
                    onClick={handleLogout}
                  >
                    <LogOut className="w-4 h-4 mr-3" />
                    Logout
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header; 