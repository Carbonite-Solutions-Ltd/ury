import React, { useEffect, useState } from 'react';
import { AlertTriangle, Bell, ChefHat, CheckCircle, Clock, X } from 'lucide-react';
import { Card, CardContent, Badge } from '../components/ui';
import { Spinner } from '../components/ui/spinner';
import { call } from '../lib/frappe-sdk';
import { formatCurrency } from '../lib/utils';
import { showToast } from '../components/ui/toast';

// @ts-ignore
const socket = window.frappe?.socketio || null;

interface KitchenNotification {
  invoice: string;
  customer_name: string;
  restaurant_table: string | null;
  posting_date: string;
  posting_time: string;
  grand_total: number;
  custom_order_status: string;
  kot_name: string | null;
  kot_status: string | null;
  kot_creation: string;
  items_count: number;
  items_list: string;
}

interface LateOrder {
  kot_name: string;
  invoice: string;
  restaurant_table: string | null;
  order_no: string | null;
  production: string | null;
  kot_creation: string;
  waiter: string | null;
  kot_type: string;
  customer_name: string | null;
  grand_total: number;
  posting_date: string;
  posting_time: string;
  owner: string;
  items_list: string;
  items_count: number;
  elapsed_minutes: number;
  over_by_minutes: number;
}

type TabKey = 'kitchen' | 'late' | 'system';

export default function Notifications() {
  const [activeTab, setActiveTab] = useState<TabKey>('kitchen');
  const [loading, setLoading] = useState(false);
  const [kitchenNotifications, setKitchenNotifications] = useState<KitchenNotification[]>([]);
  const [lateOrders, setLateOrders] = useState<LateOrder[]>([]);
  const [policyMinutes, setPolicyMinutes] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab === 'kitchen') {
      fetchKitchenNotifications();
    } else if (activeTab === 'late') {
      fetchLateOrders();
    }

    // Listen for realtime updates
    if (socket) {
      socket.on('order_served_notification', handleRealtimeNotification);
    }

    // Keep "Late" tab fresh — orders cross the threshold passively.
    let interval: ReturnType<typeof setInterval> | null = null;
    if (activeTab === 'late') {
      interval = setInterval(fetchLateOrders, 30000);
    }

    return () => {
      if (socket) {
        socket.off('order_served_notification', handleRealtimeNotification);
      }
      if (interval) clearInterval(interval);
    };
  }, [activeTab]);

  const handleRealtimeNotification = (data: any) => {
    console.log('🔔 Realtime notification received:', data);

    // Refresh notifications when new order is served
    if (activeTab === 'kitchen') {
      fetchKitchenNotifications();
    }
  };

  const fetchKitchenNotifications = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await call.get('ury.ury_pos.api.get_kitchen_notifications');
      setKitchenNotifications(response.message || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch notifications');
    } finally {
      setLoading(false);
    }
  };

  const fetchLateOrders = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await call.get('ury.ury.api.ury_kot_display.get_late_orders');
      const msg = response.message || {};
      setLateOrders(msg.orders || []);
      setPolicyMinutes(msg.policy_minutes || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch late orders');
    } finally {
      setLoading(false);
    }
  };

  const clearNotification = async (invoiceName: string) => {
    try {
      await call.post('ury.ury_pos.api.clear_notification', {
        invoice_name: invoiceName
      });
      
      // Remove from local state
      setKitchenNotifications(prev =>
        prev.filter(n => n.invoice !== invoiceName)
      );

      showToast.success('Marked as served');
    } catch (err) {
      showToast.error('Failed to mark as served');
    }
  };

  const handleTouchStart = (e: React.TouchEvent, invoiceName: string) => {
    const touch = e.touches[0];
    const startX = touch.clientX;
    
    const handleTouchMove = (moveEvent: TouchEvent) => {
      const currentX = moveEvent.touches[0].clientX;
      const diff = startX - currentX;
      
      if (diff > 100) {
        clearNotification(invoiceName);
        document.removeEventListener('touchmove', handleTouchMove);
        document.removeEventListener('touchend', handleTouchEnd);
      }
    };
    
    const handleTouchEnd = () => {
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleTouchEnd);
    };
    
    document.addEventListener('touchmove', handleTouchMove);
    document.addEventListener('touchend', handleTouchEnd);
  };

  const formatDateTime = (date: string, time: string) => {
    return new Date(date + ' ' + time).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      hour12: true
    });
  };

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-gray-900">Notifications</h1>
          <button
            onClick={() =>
              activeTab === 'late' ? fetchLateOrders() : fetchKitchenNotifications()
            }
            className="px-4 py-2 text-sm font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-md transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white border-b border-gray-200">
        <div className="px-6">
          <div className="flex space-x-8">
            <button
              onClick={() => setActiveTab('kitchen')}
              className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'kitchen'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <ChefHat className="w-5 h-5" />
                <span>Kitchen Updates</span>
                {kitchenNotifications.length > 0 && (
                  <Badge variant="default" className="ml-2 bg-green-600">
                    {kitchenNotifications.length}
                  </Badge>
                )}
              </div>
            </button>
            <button
              onClick={() => setActiveTab('late')}
              className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'late'
                  ? 'border-red-500 text-red-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-5 h-5" />
                <span>Late Orders</span>
                {lateOrders.length > 0 && (
                  <Badge variant="default" className="ml-2 bg-red-600">
                    {lateOrders.length}
                  </Badge>
                )}
              </div>
            </button>
            <button
              onClick={() => setActiveTab('system')}
              className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'system'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <Bell className="w-5 h-5" />
                <span>System Notifications</span>
              </div>
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === 'late' ? (
          loading ? (
            <div className="flex items-center justify-center h-64">
              <Spinner />
            </div>
          ) : error ? (
            <div className="text-center py-12">
              <X className="w-12 h-12 text-red-500 mx-auto mb-4" />
              <p className="text-red-600 font-medium">{error}</p>
            </div>
          ) : policyMinutes === 0 ? (
            <div className="text-center py-12">
              <AlertTriangle className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-500 text-lg">No service policy configured</p>
              <p className="text-gray-400 text-sm mt-2 max-w-md mx-auto">
                Set <span className="font-medium">Average Service Policy Time</span> on
                your POS Profile to track late orders.
              </p>
            </div>
          ) : lateOrders.length === 0 ? (
            <div className="text-center py-12">
              <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
              <p className="text-gray-700 text-lg font-medium">All orders on time</p>
              <p className="text-gray-400 text-sm mt-2">
                Policy: {policyMinutes} min. Late orders will show up here.
              </p>
            </div>
          ) : (
            <div className="max-w-4xl mx-auto space-y-3">
              <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-2 mb-2">
                <span className="font-semibold">{lateOrders.length}</span> order
                {lateOrders.length === 1 ? '' : 's'} past the{' '}
                <span className="font-semibold">{policyMinutes}-minute</span>{' '}
                service policy.
              </div>
              {lateOrders.map((order) => (
                <Card
                  key={order.kot_name}
                  className="hover:shadow-md transition-shadow relative border-l-4 border-l-red-500"
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                        <AlertTriangle className="w-5 h-5 text-red-600" />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <h3 className="text-base font-semibold text-gray-900">
                            {order.invoice}
                          </h3>
                          {order.order_no && (
                            <span className="text-xs text-gray-500">
                              #{order.order_no}
                            </span>
                          )}
                          <Badge className="bg-red-600 text-white text-xs">
                            {order.over_by_minutes > 0
                              ? `${order.over_by_minutes} min over`
                              : 'Late'}
                          </Badge>
                          {order.production && (
                            <Badge className="bg-gray-100 text-gray-700 text-xs border border-gray-300">
                              {order.production}
                            </Badge>
                          )}
                        </div>

                        <div className="flex items-center gap-4 text-sm text-gray-600 mb-2 flex-wrap">
                          {order.customer_name && (
                            <>
                              <span>{order.customer_name}</span>
                              <span className="text-gray-400">•</span>
                            </>
                          )}
                          {order.restaurant_table ? (
                            <span>Table {order.restaurant_table}</span>
                          ) : (
                            <span>Takeaway</span>
                          )}
                          <span className="text-gray-400">•</span>
                          <span>{order.items_count} item(s)</span>
                          {order.waiter && (
                            <>
                              <span className="text-gray-400">•</span>
                              <span>Waiter: {order.waiter}</span>
                            </>
                          )}
                        </div>

                        {order.items_list && (
                          <div className="bg-gray-50 rounded-md p-2 mb-2">
                            <p className="text-xs font-medium text-gray-700 mb-1">
                              Items:
                            </p>
                            <p className="text-xs text-gray-600 line-clamp-2">
                              {order.items_list}
                            </p>
                          </div>
                        )}

                        <div className="flex items-center justify-between text-xs">
                          <span className="text-red-600 flex items-center gap-1 font-medium">
                            <Clock className="w-3 h-3" />
                            {order.elapsed_minutes} min since order
                          </span>
                          <span className="font-bold text-gray-900 text-sm">
                            {formatCurrency(order.grand_total)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )
        ) : activeTab === 'kitchen' ? (
          loading ? (
            <div className="flex items-center justify-center h-64">
              <Spinner />
            </div>
          ) : error ? (
            <div className="text-center py-12">
              <X className="w-12 h-12 text-red-500 mx-auto mb-4" />
              <p className="text-red-600 font-medium">{error}</p>
            </div>
          ) : kitchenNotifications.length === 0 ? (
            <div className="text-center py-12">
              <ChefHat className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-500 text-lg">No kitchen updates</p>
              <p className="text-gray-400 text-sm mt-2">You'll be notified when orders are ready</p>
            </div>
          ) : (
            <div className="max-w-4xl mx-auto space-y-3">
              {kitchenNotifications.map((notification) => (
                <Card 
                  key={notification.invoice} 
                  className="hover:shadow-md transition-shadow relative"
                  onTouchStart={(e) => handleTouchStart(e, notification.invoice)}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      {/* Status Icon */}
                      <div className="flex-shrink-0 w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
                        <CheckCircle className="w-5 h-5 text-green-600" />
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <h3 className="text-base font-semibold text-gray-900">
                            {notification.invoice}
                          </h3>
                          <Badge className="bg-green-600 text-white text-xs">
                            Ready
                          </Badge>
                        </div>

                        <div className="flex items-center gap-4 text-sm text-gray-600 mb-2">
                          <span>{notification.customer_name}</span>
                          {notification.restaurant_table && (
                            <>
                              <span className="text-gray-400">•</span>
                              <span>Table {notification.restaurant_table}</span>
                            </>
                          )}
                          <span className="text-gray-400">•</span>
                          <span>{notification.items_count} item(s)</span>
                        </div>

                        {/* Items List */}
                        {notification.items_list && (
                          <div className="bg-gray-50 rounded-md p-2 mb-2">
                            <p className="text-xs font-medium text-gray-700 mb-1">Items:</p>
                            <p className="text-xs text-gray-600 line-clamp-2">
                              {notification.items_list}
                            </p>
                          </div>
                        )}

                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-500 flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {formatDateTime(notification.posting_date, notification.posting_time)}
                          </span>
                          <span className="font-bold text-gray-900 text-sm">
                            {formatCurrency(notification.grand_total)}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Served action — replaces the old X close icon. Marks
                        the order served + clears it from the list, which
                        drops the notification count and stops the recurring
                        every-minute reminder once the list is empty.
                        2026-07-16. */}
                    <div className="mt-3 flex justify-end">
                      <button
                        onClick={() => clearNotification(notification.invoice)}
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md bg-green-600 text-white text-sm font-semibold hover:bg-green-700 active:bg-green-800 transition-colors"
                      >
                        <CheckCircle className="w-4 h-4" />
                        Served
                      </button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )
        ) : (
          <div className="text-center py-12">
            <Bell className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <p className="text-gray-500 text-lg">No system notifications</p>
            <p className="text-gray-400 text-sm mt-2">System alerts will appear here</p>
          </div>
        )}
      </div>
    </div>
  );
}