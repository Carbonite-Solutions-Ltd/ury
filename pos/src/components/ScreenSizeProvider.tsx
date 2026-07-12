import { useState, useEffect } from 'react';
import ScreenSizeDialog from './ScreenSizeDialog';

interface ScreenSizeProviderProps {
  children: React.ReactNode;
}

// The minimum screen width (px) is configured per POS Profile
// (`custom_min_screen_width`) and cached to localStorage by the profile
// fetch (getCombinedPosProfile). This provider runs ABOVE the auth/profile
// flow, so it reads the cached value instantly on load. 0 / unset / invalid
// = NO restriction (the POS works at any size). A positive value blocks the
// POS below that width. A changed value applies on the next load.
const getMinScreenWidth = (): number => {
  try {
    const raw = localStorage.getItem('ury_min_screen_width');
    const n = raw ? parseInt(raw, 10) : 0;
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
};

const ScreenSizeProvider = ({ children }: ScreenSizeProviderProps) => {
  const [minWidth, setMinWidth] = useState<number>(getMinScreenWidth);
  const [isScreenTooSmall, setIsScreenTooSmall] = useState(false);

  useEffect(() => {
    const check = () => {
      const min = getMinScreenWidth();
      setMinWidth(min);
      setIsScreenTooSmall(min > 0 && window.innerWidth < min);
    };
    check();
    window.addEventListener('resize', check);
    // Cross-tab: re-check if the cached min width changes elsewhere.
    window.addEventListener('storage', check);
    return () => {
      window.removeEventListener('resize', check);
      window.removeEventListener('storage', check);
    };
  }, []);

  // No restriction configured (or screen is wide enough) → render the POS.
  if (isScreenTooSmall && minWidth > 0) {
    return <ScreenSizeDialog requiredWidth={minWidth} />;
  }

  return <>{children}</>;
};

export default ScreenSizeProvider;
