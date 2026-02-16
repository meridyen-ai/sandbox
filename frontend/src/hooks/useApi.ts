/**
 * API Hook for Sandbox Backend
 *
 * Provides a simple interface for making API calls to the sandbox backend.
 */

import { useState, useCallback } from 'react';
import axios, { AxiosRequestConfig } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8081';

interface ApiCallOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  data?: any;
  params?: Record<string, any>;
  headers?: Record<string, string>;
}

interface ApiResponse<T = any> {
  status: string;
  data?: T;
  message?: string;
  error?: string;
}

export function useApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const callApi = useCallback(async <T = any>(
    endpoint: string,
    options: ApiCallOptions = {}
  ): Promise<ApiResponse<T> | null> => {
    const {
      method = 'GET',
      data,
      params,
      headers = {}
    } = options;

    setLoading(true);
    setError(null);

    try {
      // Get API key from localStorage (if using authentication)
      const apiKey = localStorage.getItem('sandbox_api_key');
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }

      const config: AxiosRequestConfig = {
        method,
        url: `${API_BASE_URL}${endpoint}`,
        headers: {
          'Content-Type': 'application/json',
          ...headers,
        },
        params,
        data,
      };

      const response = await axios(config);
      return response.data;

    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'API call failed';
      setError(errorMessage);
      console.error('API Error:', err);
      throw new Error(errorMessage);

    } finally {
      setLoading(false);
    }
  }, []);

  return {
    callApi,
    loading,
    error,
    clearError: () => setError(null),
  };
}
