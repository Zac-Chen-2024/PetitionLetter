import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import zh from './locales/zh.json';

// Get saved language or detect from browser
const savedLang = localStorage.getItem('language');
const browserLang = navigator.language.startsWith('zh') ? 'zh' : 'en';
const defaultLang = savedLang || browserLang;

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    lng: defaultLang,
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
