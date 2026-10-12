/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: '#101C2D', 800: '#16263B', 700: '#1E3350', 600: '#2A4468' },
        brand: { DEFAULT: '#3478F6', dark: '#2563DB', soft: '#E8F0FE' },
        surface: '#F4F7FB',
        ink: '#0F1B2D',
        muted: '#64748B',
        line: '#E3E9F2',
        ok: { DEFAULT: '#16A34A', soft: '#E7F6EC' },
        warn: { DEFAULT: '#D97706', soft: '#FEF3DC' },
        crit: { DEFAULT: '#DC2626', soft: '#FDE8E8' },
        violet: { DEFAULT: '#7C6BD6', soft: '#EEEBFB' },
        slate2: '#5B7399',
      },
      fontFamily: {
        heading: ['Manrope', 'system-ui', 'sans-serif'],
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,28,45,0.04)',
        pop: '0 12px 32px rgba(16,28,45,0.18)',
      },
    },
  },
  plugins: [],
}
