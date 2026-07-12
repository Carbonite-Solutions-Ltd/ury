import { Monitor, Smartphone } from 'lucide-react';

interface ScreenSizeDialogProps {
  /** The admin-configured minimum width (px) this device fell short of. */
  requiredWidth: number;
}

const ScreenSizeDialog = ({ requiredWidth }: ScreenSizeDialogProps) => {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-8 max-w-md w-full mx-4 shadow-xl">
        <div className="text-center">
          {/* Icon */}
          <div className="mx-auto flex items-center justify-center h-16 w-16 rounded-full bg-blue-100 mb-6">
            <div className="relative">
              <Monitor className="h-8 w-8 text-blue-600" />
              <Smartphone className="h-4 w-4 text-red-500 absolute -top-1 -right-1" />
            </div>
          </div>

          {/* Title */}
          <h2 className="text-2xl font-bold text-gray-900 mb-4">
            Desktop Only
          </h2>

          {/* Message */}
          <div className="text-gray-600 mb-8 space-y-3">
            <p className="text-lg">
              This POS system is designed for desktop computers and tablets with larger screens.
            </p>
            <p className="text-sm">
              Please use a device with a screen width of {requiredWidth}px or
              larger. Tip: if your screen is wide enough, reset browser zoom
              (Ctrl/⌘ + 0) and maximize the window — zoom shrinks the reported
              width.
            </p>
          </div>

          {/* Current Screen Info */}
          <div className="bg-gray-50 rounded-lg p-4 mb-2">
            <p className="text-sm text-gray-600">
              Current screen width: <span className="font-semibold text-gray-800">{window.innerWidth}px</span>
            </p>
            <p className="text-sm text-gray-600">
              Required: <span className="font-semibold text-gray-800">{requiredWidth}px or larger</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ScreenSizeDialog;
