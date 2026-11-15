/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef6ff',
          100: '#d9eaff',
          200: '#bcdbff',
          300: '#8ec4ff',
          400: '#59a3ff',
          500: '#3380fc',
          600: '#1b62f1',
          700: '#144ce1',
          800: '#173fb6',
          900: '#193a8f',
          950: '#142557',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
