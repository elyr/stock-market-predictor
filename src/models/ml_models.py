"""
Machine learning models for stock price prediction.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import logging
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.metrics import accuracy_score, classification_report, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler
import xgboost as xgb
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, LSTM
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping
import joblib
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)


class StockPredictor:
    """
    Comprehensive machine learning system for stock price prediction.
    """
    
    def __init__(self, config: Dict = None):
        """Initialize with configuration."""
        self.config = config or self._default_config()
        self.models = {}
        self.scalers = {}
        self.feature_importance = {}
        self.model_performance = {}
    
    def _default_config(self) -> Dict:
        """Default configuration for ML models."""
        return {
            'random_forest': {
                'n_estimators': 100,
                'max_depth': 10,
                'min_samples_split': 5,
                'min_samples_leaf': 2,
                'random_state': 42
            },
            'xgboost': {
                'n_estimators': 200,
                'max_depth': 6,
                'learning_rate': 0.1,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'random_state': 42
            },
            'neural_network': {
                'hidden_layers': [64, 32, 16],
                'dropout_rate': 0.2,
                'epochs': 50,
                'batch_size': 32,
                'validation_split': 0.2
            },
            'lstm': {
                'units': [50, 50],
                'dropout_rate': 0.2,
                'epochs': 50,
                'batch_size': 32,
                'sequence_length': 30
            }
        }
    
    def prepare_data(self, data: pd.DataFrame, target_column: str = 'Target_Up', 
                    test_size: float = 0.2) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[str]]:
        """
        Prepare data for machine learning.
        
        Args:
            data: DataFrame with features and targets
            target_column: Name of target column
            test_size: Proportion of data for testing
        
        Returns:
            Tuple of (X_train, X_test, y_train, y_test, feature_names)
        """
        # Remove rows with missing targets
        df = data.dropna(subset=[target_column]).copy()
        
        if len(df) < 50:
            raise ValueError("Insufficient data for training (minimum 50 samples required)")
        
        # Define feature columns (exclude targets and identifiers)
        exclude_cols = [
            'Target_Up', 'Target_Direction', 'Target_Return', 
            'Future_Close', 'Future_Return', 'Symbol', 'Date'
        ]
        
        feature_columns = [col for col in df.select_dtypes(include=[np.number]).columns 
                          if col not in exclude_cols and not col.startswith('Pattern_')]
        
        # Add pattern columns back (they're binary features)
        pattern_columns = [col for col in df.columns if col.startswith('Pattern_')]
        feature_columns.extend(pattern_columns)
        
        # Prepare features and target
        X = df[feature_columns].fillna(0)
        y = df[target_column]
        
        # Split the data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Store scaler
        self.scalers['main'] = scaler
        
        logger.info(f"Data prepared: {X_train_scaled.shape[0]} training, {X_test_scaled.shape[0]} test samples")
        logger.info(f"Features: {len(feature_columns)}")
        
        return X_train_scaled, X_test_scaled, y_train.values, y_test.values, feature_columns
    
    def train_random_forest(self, X_train: np.ndarray, y_train: np.ndarray, 
                           X_test: np.ndarray, y_test: np.ndarray, 
                           feature_names: List[str]) -> Dict[str, Any]:
        """
        Train Random Forest model.
        
        Args:
            X_train: Training features
            y_train: Training targets
            X_test: Test features
            y_test: Test targets
            feature_names: List of feature names
        
        Returns:
            Dictionary with model performance metrics
        """
        logger.info("Training Random Forest model...")
        
        # Initialize model
        rf_config = self.config['random_forest']
        model = RandomForestClassifier(**rf_config)
        
        # Train model
        model.fit(X_train, y_train)
        
        # Make predictions
        y_pred_train = model.predict(X_train)
        y_pred_test = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        
        # Calculate metrics
        train_accuracy = accuracy_score(y_train, y_pred_train)
        test_accuracy = accuracy_score(y_test, y_pred_test)
        
        # Cross-validation
        cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring='accuracy')
        
        # Feature importance
        feature_importance = dict(zip(feature_names, model.feature_importances_))
        
        # Store model and results
        self.models['random_forest'] = model
        self.feature_importance['random_forest'] = feature_importance
        
        performance = {
            'train_accuracy': train_accuracy,
            'test_accuracy': test_accuracy,
            'cv_mean': cv_scores.mean(),
            'cv_std': cv_scores.std(),
            'predictions': y_pred_test,
            'probabilities': y_pred_proba
        }
        
        self.model_performance['random_forest'] = performance
        
        logger.info(f"Random Forest - Test Accuracy: {test_accuracy:.4f}, CV: {cv_scores.mean():.4f} (+/- {cv_scores.std()*2:.4f})")
        
        return performance
    
    def train_xgboost(self, X_train: np.ndarray, y_train: np.ndarray, 
                     X_test: np.ndarray, y_test: np.ndarray, 
                     feature_names: List[str]) -> Dict[str, Any]:
        """
        Train XGBoost model.
        
        Args:
            X_train: Training features
            y_train: Training targets
            X_test: Test features
            y_test: Test targets
            feature_names: List of feature names
        
        Returns:
            Dictionary with model performance metrics
        """
        logger.info("Training XGBoost model...")
        
        # Initialize model
        xgb_config = self.config['xgboost']
        model = xgb.XGBClassifier(**xgb_config)
        
        # Train model
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        
        # Make predictions
        y_pred_train = model.predict(X_train)
        y_pred_test = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        
        # Calculate metrics
        train_accuracy = accuracy_score(y_train, y_pred_train)
        test_accuracy = accuracy_score(y_test, y_pred_test)
        
        # Cross-validation
        cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring='accuracy')
        
        # Feature importance
        feature_importance = dict(zip(feature_names, model.feature_importances_))
        
        # Store model and results
        self.models['xgboost'] = model
        self.feature_importance['xgboost'] = feature_importance
        
        performance = {
            'train_accuracy': train_accuracy,
            'test_accuracy': test_accuracy,
            'cv_mean': cv_scores.mean(),
            'cv_std': cv_scores.std(),
            'predictions': y_pred_test,
            'probabilities': y_pred_proba
        }
        
        self.model_performance['xgboost'] = performance
        
        logger.info(f"XGBoost - Test Accuracy: {test_accuracy:.4f}, CV: {cv_scores.mean():.4f} (+/- {cv_scores.std()*2:.4f})")
        
        return performance
    
    def train_neural_network(self, X_train: np.ndarray, y_train: np.ndarray, 
                           X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, Any]:
        """
        Train Neural Network model.
        
        Args:
            X_train: Training features
            y_train: Training targets
            X_test: Test features
            y_test: Test targets
        
        Returns:
            Dictionary with model performance metrics
        """
        logger.info("Training Neural Network model...")
        
        nn_config = self.config['neural_network']
        
        # Build model
        model = Sequential()
        
        # Input layer
        model.add(Dense(nn_config['hidden_layers'][0], 
                       input_dim=X_train.shape[1], 
                       activation='relu'))
        model.add(Dropout(nn_config['dropout_rate']))
        
        # Hidden layers
        for units in nn_config['hidden_layers'][1:]:
            model.add(Dense(units, activation='relu'))
            model.add(Dropout(nn_config['dropout_rate']))
        
        # Output layer
        model.add(Dense(1, activation='sigmoid'))
        
        # Compile model
        model.compile(optimizer=Adam(learning_rate=0.001),
                     loss='binary_crossentropy',
                     metrics=['accuracy'])
        
        # Train model
        early_stopping = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        
        history = model.fit(X_train, y_train,
                          epochs=nn_config['epochs'],
                          batch_size=nn_config['batch_size'],
                          validation_split=nn_config['validation_split'],
                          callbacks=[early_stopping],
                          verbose=0)
        
        # Make predictions
        y_pred_train = (model.predict(X_train) > 0.5).astype(int).flatten()
        y_pred_test = (model.predict(X_test) > 0.5).astype(int).flatten()
        y_pred_proba = model.predict(X_test).flatten()
        
        # Calculate metrics
        train_accuracy = accuracy_score(y_train, y_pred_train)
        test_accuracy = accuracy_score(y_test, y_pred_test)
        
        # Store model and results
        self.models['neural_network'] = model
        
        performance = {
            'train_accuracy': train_accuracy,
            'test_accuracy': test_accuracy,
            'history': history.history,
            'predictions': y_pred_test,
            'probabilities': y_pred_proba
        }
        
        self.model_performance['neural_network'] = performance
        
        logger.info(f"Neural Network - Test Accuracy: {test_accuracy:.4f}")
        
        return performance
    
    def prepare_lstm_data(self, data: pd.DataFrame, feature_columns: List[str], 
                         target_column: str = 'Target_Up', 
                         sequence_length: int = 30) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare data for LSTM model.
        
        Args:
            data: DataFrame with time series data
            feature_columns: List of feature column names
            target_column: Target column name
            sequence_length: Length of input sequences
        
        Returns:
            Tuple of (X_train, X_test, y_train, y_test)
        """
        # Sort by date
        df = data.sort_index().copy()
        
        # Remove rows with missing targets
        df = df.dropna(subset=[target_column])
        
        # Prepare features and targets
        features = df[feature_columns].fillna(0).values
        targets = df[target_column].values
        
        # Create sequences
        X, y = [], []
        
        for i in range(sequence_length, len(features)):
            X.append(features[i-sequence_length:i])
            y.append(targets[i])
        
        X, y = np.array(X), np.array(y)
        
        # Split data (use last 20% for testing)
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        logger.info(f"LSTM data prepared: {X_train.shape[0]} training, {X_test.shape[0]} test sequences")
        
        return X_train, X_test, y_train, y_test
    
    def train_lstm(self, data: pd.DataFrame, feature_columns: List[str]) -> Dict[str, Any]:
        """
        Train LSTM model for time series prediction.
        
        Args:
            data: DataFrame with time series data
            feature_columns: List of feature column names
        
        Returns:
            Dictionary with model performance metrics
        """
        logger.info("Training LSTM model...")
        
        lstm_config = self.config['lstm']
        
        # Prepare LSTM data
        X_train, X_test, y_train, y_test = self.prepare_lstm_data(
            data, feature_columns, sequence_length=lstm_config['sequence_length']
        )
        
        if len(X_train) < 50:
            logger.warning("Insufficient data for LSTM training")
            return {}
        
        # Build LSTM model
        model = Sequential()
        
        # First LSTM layer
        model.add(LSTM(lstm_config['units'][0], 
                      return_sequences=True if len(lstm_config['units']) > 1 else False,
                      input_shape=(X_train.shape[1], X_train.shape[2])))
        model.add(Dropout(lstm_config['dropout_rate']))
        
        # Additional LSTM layers
        for i, units in enumerate(lstm_config['units'][1:]):
            return_sequences = i < len(lstm_config['units']) - 2
            model.add(LSTM(units, return_sequences=return_sequences))
            model.add(Dropout(lstm_config['dropout_rate']))
        
        # Dense output layer
        model.add(Dense(1, activation='sigmoid'))
        
        # Compile model
        model.compile(optimizer=Adam(learning_rate=0.001),
                     loss='binary_crossentropy',
                     metrics=['accuracy'])
        
        # Train model
        early_stopping = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        
        history = model.fit(X_train, y_train,
                          epochs=lstm_config['epochs'],
                          batch_size=lstm_config['batch_size'],
                          validation_data=(X_test, y_test),
                          callbacks=[early_stopping],
                          verbose=0)
        
        # Make predictions
        y_pred_test = (model.predict(X_test) > 0.5).astype(int).flatten()
        y_pred_proba = model.predict(X_test).flatten()
        
        # Calculate metrics
        test_accuracy = accuracy_score(y_test, y_pred_test)
        
        # Store model and results
        self.models['lstm'] = model
        
        performance = {
            'test_accuracy': test_accuracy,
            'history': history.history,
            'predictions': y_pred_test,
            'probabilities': y_pred_proba
        }
        
        self.model_performance['lstm'] = performance
        
        logger.info(f"LSTM - Test Accuracy: {test_accuracy:.4f}")
        
        return performance
    
    def train_all_models(self, data: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Train all available models.
        
        Args:
            data: DataFrame with features and targets
        
        Returns:
            Dictionary with all model performances
        """
        logger.info("Training all models...")
        
        # Prepare data for standard ML models
        X_train, X_test, y_train, y_test, feature_names = self.prepare_data(data)
        
        # Train models
        performances = {}
        
        try:
            performances['random_forest'] = self.train_random_forest(
                X_train, y_train, X_test, y_test, feature_names
            )
        except Exception as e:
            logger.error(f"Error training Random Forest: {str(e)}")
        
        try:
            performances['xgboost'] = self.train_xgboost(
                X_train, y_train, X_test, y_test, feature_names
            )
        except Exception as e:
            logger.error(f"Error training XGBoost: {str(e)}")
        
        try:
            performances['neural_network'] = self.train_neural_network(
                X_train, y_train, X_test, y_test
            )
        except Exception as e:
            logger.error(f"Error training Neural Network: {str(e)}")
        
        try:
            performances['lstm'] = self.train_lstm(data, feature_names)
        except Exception as e:
            logger.error(f"Error training LSTM: {str(e)}")
        
        return performances
    
    def predict(self, data: pd.DataFrame, model_name: str = 'ensemble') -> Dict[str, Any]:
        """
        Make predictions using trained models.
        
        Args:
            data: DataFrame with features
            model_name: Name of model to use or 'ensemble' for ensemble prediction
        
        Returns:
            Dictionary with predictions and probabilities
        """
        if not self.models:
            raise ValueError("No trained models available. Train models first.")
        
        # Prepare features
        exclude_cols = [
            'Target_Up', 'Target_Direction', 'Target_Return', 
            'Future_Close', 'Future_Return', 'Symbol', 'Date'
        ]
        
        feature_columns = [col for col in data.select_dtypes(include=[np.number]).columns 
                          if col not in exclude_cols and not col.startswith('Pattern_')]
        
        pattern_columns = [col for col in data.columns if col.startswith('Pattern_')]
        feature_columns.extend(pattern_columns)
        
        X = data[feature_columns].fillna(0)
        
        if model_name == 'ensemble':
            # Ensemble prediction
            predictions = []
            probabilities = []
            
            for name, model in self.models.items():
                if name in ['random_forest', 'xgboost']:
                    X_scaled = self.scalers['main'].transform(X)
                    pred = model.predict(X_scaled)
                    prob = model.predict_proba(X_scaled)[:, 1]
                    predictions.append(pred)
                    probabilities.append(prob)
                elif name == 'neural_network':
                    X_scaled = self.scalers['main'].transform(X)
                    prob = model.predict(X_scaled).flatten()
                    pred = (prob > 0.5).astype(int)
                    predictions.append(pred)
                    probabilities.append(prob)
            
            if predictions:
                # Average predictions
                ensemble_prob = np.mean(probabilities, axis=0)
                ensemble_pred = (ensemble_prob > 0.5).astype(int)
                
                return {
                    'predictions': ensemble_pred,
                    'probabilities': ensemble_prob,
                    'individual_predictions': {
                        name: pred for name, pred in zip(self.models.keys(), predictions)
                    },
                    'individual_probabilities': {
                        name: prob for name, prob in zip(self.models.keys(), probabilities)
                    }
                }
        
        else:
            # Single model prediction
            if model_name not in self.models:
                raise ValueError(f"Model {model_name} not found")
            
            model = self.models[model_name]
            
            if model_name in ['random_forest', 'xgboost']:
                X_scaled = self.scalers['main'].transform(X)
                pred = model.predict(X_scaled)
                prob = model.predict_proba(X_scaled)[:, 1]
            elif model_name == 'neural_network':
                X_scaled = self.scalers['main'].transform(X)
                prob = model.predict(X_scaled).flatten()
                pred = (prob > 0.5).astype(int)
            
            return {
                'predictions': pred,
                'probabilities': prob
            }
    
    def get_feature_importance(self, model_name: str = 'random_forest', top_n: int = 20) -> List[Tuple[str, float]]:
        """
        Get feature importance from trained model.
        
        Args:
            model_name: Name of model
            top_n: Number of top features to return
        
        Returns:
            List of (feature_name, importance) tuples
        """
        if model_name not in self.feature_importance:
            return []
        
        importance = self.feature_importance[model_name]
        sorted_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)
        
        return sorted_features[:top_n]
    
    def save_models(self, filepath: str) -> None:
        """Save trained models to file."""
        model_data = {
            'models': self.models,
            'scalers': self.scalers,
            'feature_importance': self.feature_importance,
            'model_performance': self.model_performance,
            'config': self.config
        }
        
        joblib.dump(model_data, filepath)
        logger.info(f"Models saved to {filepath}")
    
    def load_models(self, filepath: str) -> None:
        """Load trained models from file."""
        model_data = joblib.load(filepath)
        
        self.models = model_data['models']
        self.scalers = model_data['scalers']
        self.feature_importance = model_data['feature_importance']
        self.model_performance = model_data['model_performance']
        self.config = model_data['config']
        
        logger.info(f"Models loaded from {filepath}")


if __name__ == "__main__":
    # Example usage
    from ..data import DataCollector, DataPreprocessor
    from ..analysis import TechnicalAnalyzer
    
    # Collect and prepare data
    collector = DataCollector()
    preprocessor = DataPreprocessor()
    analyzer = TechnicalAnalyzer()
    predictor = StockPredictor()
    
    # Get sample data
    symbol = 'AAPL'
    data = collector.fetch_stock_data(symbol)
    
    if data is not None:
        print(f"Training models for {symbol}...")
        
        # Preprocess data
        data = preprocessor.clean_stock_data(data)
        data = preprocessor.add_basic_features(data)
        data = preprocessor.add_moving_averages(data)
        data = preprocessor.add_momentum_features(data)
        data = preprocessor.add_pattern_features(data)
        data = preprocessor.add_support_resistance(data)
        
        # Add technical indicators
        data = analyzer.calculate_all_indicators(data)
        
        # Create target
        data = preprocessor.create_target_variable(data)
        
        # Train models
        performances = predictor.train_all_models(data)
        
        print("\nModel Performances:")
        for model_name, perf in performances.items():
            if 'test_accuracy' in perf:
                print(f"{model_name}: {perf['test_accuracy']:.4f}")
        
        # Show feature importance
        top_features = predictor.get_feature_importance('random_forest', top_n=10)
        print(f"\nTop 10 most important features:")
        for feature, importance in top_features:
            print(f"{feature}: {importance:.4f}")
        
        # Make prediction on recent data
        recent_data = data.tail(1)
        prediction = predictor.predict(recent_data, model_name='ensemble')
        print(f"\nEnsemble prediction for next day: {prediction['predictions'][0]} (prob: {prediction['probabilities'][0]:.3f})")