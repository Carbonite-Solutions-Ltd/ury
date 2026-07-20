import { useEffect, useState } from 'react';
import { MessageSquare, X } from 'lucide-react';
import { Button } from './ui';

interface CommentDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (comment: string) => void;
  initialComment?: string;
  /** Heading — defaults to the order-level wording. */
  title?: string;
  /** Field label above the textarea. */
  label?: string;
  placeholder?: string;
}

const CommentDialog = ({
  isOpen,
  onClose,
  onSave,
  initialComment = '',
  title = 'Order Comments',
  label = 'Add comments for this order',
  placeholder = 'Enter any special instructions or comments...',
}: CommentDialogProps) => {
  const [comment, setComment] = useState(initialComment);

  // The dialog stays mounted (it just renders null when closed), so the
  // state would otherwise persist between opens — showing the PREVIOUS
  // item's note when you open a different one. Re-seed on every open.
  // 2026-07-16.
  useEffect(() => {
    if (isOpen) setComment(initialComment);
  }, [isOpen, initialComment]);

  const handleSave = () => {
    onSave(comment);
    onClose();
  };

  const handleCancel = () => {
    setComment(initialComment);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-5 h-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          </div>
          <Button
            onClick={handleCancel}
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
        
        <div className="mb-6">
          <label htmlFor="comment" className="block text-sm font-medium text-gray-700 mb-2">
            {label}
          </label>
          <textarea
            id="comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={placeholder}
            className="w-full h-32 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none"
            autoFocus
          />
        </div>
        
        <div className="flex gap-3 justify-end">
          <Button
            onClick={handleCancel}
            variant="outline"
            className="px-4 py-2"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700"
          >
            Save Comment
          </Button>
        </div>
      </div>
    </div>
  );
};

export default CommentDialog; 