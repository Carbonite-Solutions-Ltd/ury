import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { storage } from './storage';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(amount: number): string {
  const symbol = storage.getItem('currencySymbol');
  return `${symbol} ${amount}`;
} 

export const hasRole = (roleName: string): boolean => {
  try {
    // @ts-ignore
    const userRoles = window.frappe?.boot?.user?.roles || [];
    return userRoles.includes(roleName);
  } catch (error) {
    console.error('Error checking user role:', error);
    return false;
  }
};
