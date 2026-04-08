import { toast, ToastContainer } from 'react-toastify';
import { CheckCircle, XCircle, Info, ExternalLink } from 'lucide-react';
import 'react-toastify/dist/ReactToastify.css';

// Custom CSS for toast styling
import './toast.css';

const toastIcons = {
  success: <CheckCircle className="w-5 h-5" />,
  error: <XCircle className="w-5 h-5" />,
  info: <Info className="w-5 h-5" />,
};

/**
 * Rich toast content shape. A toast can be either a plain string (the
 * original shorthand) or a structured object with a title, optional
 * description, and an optional action button. The action button is
 * rendered only when both `action.label` and `action.onClick` are set —
 * callers that want role-gated actions should pass `undefined` for
 * users who shouldn't see the button.
 */
export interface RichToastContent {
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

type ToastContent = string | RichToastContent;

/**
 * Render rich content inside react-toastify. The library accepts JSX
 * children, so we return a compact layout with the title on top, the
 * body below, and an optional button aligned to the end.
 */
const renderRichContent = (content: RichToastContent) => (
  <div className="flex flex-col gap-1">
    <div className="font-semibold text-sm leading-snug">{content.title}</div>
    {content.description && (
      <div className="text-xs leading-snug opacity-90">{content.description}</div>
    )}
    {content.action && (
      <button
        onClick={(e) => {
          e.stopPropagation();
          content.action!.onClick();
        }}
        className="mt-2 inline-flex items-center gap-1.5 self-start rounded-md bg-white/20 hover:bg-white/30 px-2.5 py-1 text-xs font-medium text-white transition-colors"
      >
        <ExternalLink className="w-3 h-3" />
        {content.action.label}
      </button>
    )}
  </div>
);

const resolveContent = (content: ToastContent) =>
  typeof content === 'string' ? content : renderRichContent(content);

/**
 * A rich toast (with action button) defaults to a longer autoClose and
 * disables closeOnClick so the user has time to hit the action.
 */
const resolveOptions = (content: ToastContent) => {
  if (typeof content === 'string' || !content.action) {
    return { autoClose: 2000 as number | false, closeOnClick: true };
  }
  return { autoClose: 8000 as number | false, closeOnClick: false };
};

export const showToast = {
  success: (content: ToastContent) => {
    const { autoClose, closeOnClick } = resolveOptions(content);
    toast.success(resolveContent(content), {
      position: 'top-right',
      autoClose,
      hideProgressBar: false,
      closeOnClick,
      pauseOnHover: true,
      draggable: true,
      progress: undefined,
      theme: 'colored',
      icon: toastIcons.success,
      className: 'toast-success',
    });
  },
  error: (content: ToastContent) => {
    const { autoClose, closeOnClick } = resolveOptions(content);
    toast.error(resolveContent(content), {
      position: 'top-right',
      autoClose,
      hideProgressBar: false,
      closeOnClick,
      pauseOnHover: true,
      draggable: true,
      progress: undefined,
      theme: 'colored',
      icon: toastIcons.error,
      className: 'toast-error',
    });
  },
  info: (content: ToastContent) => {
    const { autoClose, closeOnClick } = resolveOptions(content);
    toast.info(resolveContent(content), {
      position: 'top-right',
      autoClose,
      hideProgressBar: false,
      closeOnClick,
      pauseOnHover: true,
      draggable: true,
      progress: undefined,
      theme: 'colored',
      icon: toastIcons.info,
      className: 'toast-info',
    });
  },
};

export const ToastProvider = () => {
  return (
    <ToastContainer
      position="top-right"
      autoClose={2000}
      hideProgressBar={false}
      newestOnTop
      closeOnClick
      rtl={false}
      pauseOnFocusLoss
      draggable
      pauseOnHover
      theme="colored"
    />
  );
};
