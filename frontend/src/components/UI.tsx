// Composants UI réutilisables.
import React from 'react'

export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizes = { sm: 'w-4 h-4', md: 'w-8 h-8', lg: 'w-12 h-12' }
  return (
    <div className={`${sizes[size]} animate-spin rounded-full border-2 border-brand-200 border-t-brand-600`} />
  )
}

export function Button({
  children, onClick, variant = 'primary', size = 'md', disabled = false, className = '', type = 'button',
}: {
  children: React.ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  className?: string
  type?: 'button' | 'submit'
}) {
  const variants = {
    primary: 'bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-300',
    secondary: 'bg-gray-100 text-gray-800 hover:bg-gray-200 disabled:bg-gray-50',
    danger: 'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300',
    ghost: 'bg-transparent text-gray-600 hover:bg-gray-100 disabled:text-gray-300',
  }
  const sizes = {
    sm: 'px-2 py-1 text-sm rounded',
    md: 'px-4 py-2 rounded-lg',
    lg: 'px-6 py-3 text-lg rounded-lg',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${variants[variant]} ${sizes[size]} font-medium transition-colors disabled:cursor-not-allowed ${className}`}
    >
      {children}
    </button>
  )
}

export function Input({
  value, onChange, placeholder, type = 'text', className = '', maxLength, onKeyDown,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  className?: string
  maxLength?: number
  onKeyDown?: (e: React.KeyboardEvent) => void
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      maxLength={maxLength}
      className={`px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent ${className}`}
    />
  )
}

export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white rounded-xl shadow-sm border border-gray-200 p-4 ${className}`}>
      {children}
    </div>
  )
}

export function Badge({ children, color = 'gray' }: { children: React.ReactNode; color?: string }) {
  const colors: Record<string, string> = {
    gray: 'bg-gray-100 text-gray-700',
    green: 'bg-green-100 text-green-700',
    red: 'bg-red-100 text-red-700',
    blue: 'bg-brand-100 text-brand-700',
    yellow: 'bg-yellow-100 text-yellow-700',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${colors[color] || colors.gray}`}>
      {children}
    </span>
  )
}

export function Modal({
  open, onClose, title, children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function ConfirmDialog({
  open, onConfirm, onCancel, message,
}: {
  open: boolean
  onConfirm: () => void
  onCancel: () => void
  message: string
}) {
  return (
    <Modal open={open} onClose={onCancel} title="Confirmation">
      <p className="text-gray-700 mb-4">{message}</p>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>Annuler</Button>
        <Button variant="danger" onClick={onConfirm}>Confirmer</Button>
      </div>
    </Modal>
  )
}
