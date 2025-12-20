/**
 * Configuration Service - GCS-based config loader for GAS
 * 
 * Loads unified configuration from GCS with Script Properties fallback.
 * Provides a Single Source of Truth for system configuration.
 */

class ConfigService {
  constructor() {
    this._cache = null;
    this._cacheTime = null;
    this.CACHE_TTL = 300000; // 5 minutes in milliseconds
  }
  
  /**
   * Get configuration (with caching)
   * @returns {Object} Configuration object
   */
  getConfig() {
    // Check cache validity
    if (this._cache && this._cacheTime) {
      const now = new Date().getTime();
      if (now - this._cacheTime < this.CACHE_TTL) {
        return this._cache;
      }
    }
    
    // Load from GCS
    try {
      const config = this._loadFromGCS();
      this._cache = config;
      this._cacheTime = new Date().getTime();
      console.log('Config loaded from GCS');
      return config;
    } catch (e) {
      console.warn('GCS config load failed, using Script Properties fallback: ' + e);
      return this._buildFromProperties();
    }
  }
  
  /**
   * Load configuration from GCS
   * @private
   */
  _loadFromGCS() {
    const props = PropertiesService.getScriptProperties();
    const bucketName = props.getProperty('GCS_BUCKET');
    
    if (!bucketName) {
      throw new Error('GCS_BUCKET not set in Script Properties');
    }
    
    const url = `https://storage.googleapis.com/${bucketName}/config/system_config.json`;
    const response = UrlFetchApp.fetch(url, {
      headers: { 'Authorization': 'Bearer ' + ScriptApp.getOAuthToken() },
      muteHttpExceptions: true
    });
    
    if (response.getResponseCode() !== 200) {
      throw new Error('Failed to fetch config: ' + response.getResponseCode());
    }
    
    return JSON.parse(response.getContentText());
  }
  
  /**
   * Build configuration from Script Properties (fallback)
   * @private
   */
  _buildFromProperties() {
    const props = PropertiesService.getScriptProperties();
    
    return {
      version: "1.0-fallback",
      gemini: {
        model_id: "gemini-2.0-flash"
      },
      folders: {
        source_folders: JSON.parse(props.getProperty('SOURCE_FOLDERS') || '{}'),
        destination_folders: JSON.parse(props.getProperty('PDF_DESTINATION_FOLDERS') || '{}'),
        scan_raw_folder_id: props.getProperty('PDF_SCAN_RAW_FOLDER_ID') || '',
        fallback_folder_id: props.getProperty('PDF_FALLBACK_FOLDER_ID') || ''
      },
      notifications: {
        alert_email: props.getProperty('ALERT_EMAIL') || '',
        enabled: props.getProperty('ALERTS_ENABLED') === 'true'
      },
      cloud_function_url: props.getProperty('CLOUD_FUNCTION_URL') || ''
    };
  }
  
  /**
   * Get nested config value using dot notation
   * @param {string} keyPath - Dot-separated path (e.g., 'gemini.model_id')
   * @param {*} defaultValue - Default value if not found
   * @returns {*} Configuration value or default
   */
  get(keyPath, defaultValue = null) {
    const config = this.getConfig();
    const keys = keyPath.split('.');
    
    let value = config;
    for (const key of keys) {
      if (value && typeof value === 'object' && key in value) {
        value = value[key];
      } else {
        return defaultValue;
      }
    }
    
    return value;
  }
  
  /**
   * Refresh configuration (clear cache and reload)
   */
  refresh() {
    this._cache = null;
    this._cacheTime = null;
    return this.getConfig();
  }
}
