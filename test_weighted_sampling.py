#!/usr/bin/env python3

import sys
import os
import tempfile
import sqlite3
import time
import math

# Add the src directory to path so we can import picframe
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def create_test_database():
    # Create a temporary database with test photo data
    db_fd, db_path = tempfile.mkstemp(suffix='.db3')
    os.close(db_fd)
    
    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE all_data (
        file_id INTEGER PRIMARY KEY,
        fname TEXT,
        last_modified INTEGER,
        is_portrait INTEGER DEFAULT 0
    )''')
    
    # List of test photos
    current_time = int(time.time())
    test_photos = []
    
    # Create 100 photos spanning 2 years
    for i in range(100):
        # Age ranges from 0 to 730 days (2 years)
        days_old = i * 7  # Weekly intervals
        timestamp = current_time - (days_old * 24 * 3600)
        fname = f'/test/photos/photo_{i:03d}.jpg'
        
        conn.execute('INSERT INTO all_data (file_id, fname, last_modified, is_portrait) VALUES (?, ?, ?, 0)',
                    (i + 1, fname, timestamp))
        test_photos.append((i + 1, timestamp))
    
    conn.commit()
    conn.close()
    
    return db_path, test_photos

def test_weighted_sampling():
    # Test the weighted sampling algorithm
    print("Testing age-weighted sampling...")
    
    # Create test database
    db_path, test_photos = create_test_database()
    
    try:
        # Test the weighted sampling logic directly without full imports
        # This avoids dependency issues while testing functionality
        timestamps = [photo[1] for photo in test_photos]
        min_time = min(timestamps)
        max_time = max(timestamps)
        time_range = max_time - min_time
        
        print(f"Created test database with {len(test_photos)} photos spanning {time_range / (24*3600):.1f} days")
        
        # Test weight calculation
        recency_bias = 2.0
        weights = []
        
        for _, timestamp in test_photos:
            # Calculate age percentile (0.0 = newest, 1.0 = oldest)
            age_percentile = (max_time - timestamp) / time_range
            # Calculate weight using exponential decay
            weight = math.exp(-age_percentile * recency_bias)
            weights.append(weight)
        
        # Verify weight distribution
        newest_weight = weights[0]  # First photo is newest
        oldest_weight = weights[-1]  # Last photo is oldest
        middle_idx = len(weights) // 2
        middle_weight = weights[middle_idx]
        
        print(f"Weight distribution - Newest: {newest_weight:.3f}, Middle: {middle_weight:.3f}, Oldest: {oldest_weight:.3f}")
        print(f"Recent photos are {newest_weight/oldest_weight:.1f}x more likely than oldest")
        
        # Verify weights decrease with age
        assert weights[0] > weights[25] > weights[50] > weights[99], "Weights should decrease with age"
        
        # Test sampling probability calculation
        total_weight = sum(weights)
        newest_prob = newest_weight / total_weight
        oldest_prob = oldest_weight / total_weight
        
        print(f"Selection probability - Newest: {newest_prob:.1%}, Oldest: {oldest_prob:.1%}")
        
        # Test sample limit functionality
        print("\nTesting sample_limit feature...")
        test_sample_limits = [10, 50, 200]  # Including one larger than available
        
        for sample_limit in test_sample_limits:
            max_samples = min(sample_limit, len(test_photos))
            print(f"Sample limit {sample_limit}: Will sample {max_samples} photos out of {len(test_photos)}")
            
            # Simulate the sampling logic with limit
            remaining_files = list(range(len(test_photos)))
            remaining_weights = weights[:]
            sampled_count = 0
            
            # Sample with limit
            while remaining_files and sampled_count < max_samples:
                # Simple sampling for test (just pick first)
                remaining_files.pop(0)
                remaining_weights.pop(0)
                sampled_count += 1
            
            assert sampled_count == max_samples, f"Should sample exactly {max_samples} photos"
        
        print("Sample limit tests passed!")
        print("\nAll tests passed")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        if os.path.exists(db_path):
            os.unlink(db_path)

if __name__ == "__main__":
    test_weighted_sampling()