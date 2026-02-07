// Simple translation hook (no-op for sandbox)
export const useTranslation = () => {
  return {
    t: (key: string) => key,
  };
};
