import { useEffect, useState } from 'react';
import { checkPOSOpening, validatePOSClose } from '../lib/pos-opening-api';
import { usePOSStore } from '../store/pos-store';
import POSOpeningDialog from './POSOpeningDialog';

interface POSOpeningProviderProps {
  children: React.ReactNode;
}

type ValidationType = 'opening' | 'closing' | null;

interface ValidationState {
  type: ValidationType;
  unclosedEntry: string | null;
}

const POSOpeningProvider = ({ children }: POSOpeningProviderProps) => {
  const [validation, setValidation] = useState<ValidationState>({
    type: null,
    unclosedEntry: null,
  });
  const [isLoading, setIsLoading] = useState(true);
  const { posProfile } = usePOSStore();

  const checkPOSStatus = async () => {
    try {
      setIsLoading(true);

      const openingResponse = await checkPOSOpening();
      if (openingResponse.message === 1) {
        setValidation({ type: 'opening', unclosedEntry: null });
        return;
      }

      // POS is open for the branch. If the daily-close rule is on, also
      // verify there's no unclosed previous-day entry for this profile.
      if (posProfile?.custom_daily_pos_close === 1) {
        try {
          const closeResponse = await validatePOSClose(posProfile.name);
          const msg = closeResponse.message;

          // Backend returns {status, unclosed_entry?} (new) but older
          // servers may still return the string "Failed"/"Success".
          if (typeof msg === 'string') {
            if (msg === 'Failed') {
              setValidation({ type: 'closing', unclosedEntry: null });
              return;
            }
          } else if (msg && msg.status === 'Failed') {
            setValidation({
              type: 'closing',
              unclosedEntry: msg.unclosed_entry || null,
            });
            return;
          }
        } catch (error) {
          console.error('Failed to validate POS close status:', error);
          setValidation({ type: 'closing', unclosedEntry: null });
          return;
        }
      }

      setValidation({ type: null, unclosedEntry: null });
    } catch (error) {
      console.error('Failed to check POS opening status:', error);
      // On failure, assume POS is not opened so the user gets an
      // actionable screen rather than a silent broken POS page.
      setValidation({ type: 'opening', unclosedEntry: null });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // Only check once the POS profile is loaded — we need it for the
    // captain-detection logic in the opening dialog.
    if (posProfile) {
      checkPOSStatus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [posProfile]);

  if (isLoading) {
    return (
      <div className="fixed inset-0 bg-white flex items-center justify-center z-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Checking POS status...</p>
        </div>
      </div>
    );
  }

  if (validation.type) {
    // After a successful open inside the dialog we do a full reload so the
    // menu items, categories, payment modes and POS profile all refetch
    // cleanly — the dialog already clears sessionStorage before calling us.
    // See CLAUDE.md "Fixes log" for the reload-cache rationale.
    const handleOpened = () => window.location.reload();

    return (
      <POSOpeningDialog
        type={validation.type}
        unclosedEntry={validation.unclosedEntry}
        onOpened={handleOpened}
      />
    );
  }

  return <>{children}</>;
};

export default POSOpeningProvider;
