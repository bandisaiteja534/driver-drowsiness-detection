// Live Detection Page JavaScript
let video = document.getElementById('videoElement');
let detectionInterval = null;
let isDetecting = false;
// Get alarm audio path from data attribute or use default
let alarmAudioPath = document.body.getAttribute('data-alarm-path') || '/static/assets/alarm.mp3';
let alarmAudio = new Audio(alarmAudioPath);
alarmAudio.loop = true;

// Video feed will be loaded automatically via img src
document.getElementById('statusValue').textContent = 'Ready to Start';

// Ensure video feed loads on page load
window.addEventListener('load', function() {
	// Add cache-busting parameter to ensure fresh load
	video.src = '/drowsy/api/video_feed?t=' + new Date().getTime();
	
	// Handle video load errors
	video.onerror = function() {
		console.error('Video feed error, retrying...');
		setTimeout(function() {
			video.src = '/drowsy/api/video_feed?t=' + new Date().getTime();
		}, 1000);
	};
});

function startDetection() {
	isDetecting = true;

	// Start the Python detection system
	fetch('/drowsy/api/start_detection', { method: 'POST' })
		.then(response => response.json())
		.then(data => {
			if (data.success) {
				// Start fetching detection data
				detectionInterval = setInterval(function () {
					fetchDetectionData();
				}, 200); // Update every 200ms

				// Update video feed with cache-busting
				video.src = '/drowsy/api/video_feed?t=' + new Date().getTime();
				document.getElementById('statusValue').textContent = 'Monitoring';
				
				// Ensure video loads
				video.onerror = function() {
					console.error('Video feed error after start, retrying...');
					setTimeout(function() {
						video.src = '/drowsy/api/video_feed?t=' + new Date().getTime();
					}, 1000);
				};
			} else {
				alert('Failed to start detection: ' + data.message);
				isDetecting = false;
			}
		})
		.catch(err => {
			console.error('Error starting detection:', err);
			alert('Error starting detection system');
			isDetecting = false;
		});
}

function stopDetection() {
	isDetecting = false;

	if (detectionInterval) {
		clearInterval(detectionInterval);
		detectionInterval = null;
	}

	// Stop the Python detection system
	fetch('/drowsy/api/stop_detection', { method: 'POST' })
		.catch(err => console.error('Error stopping detection:', err));

	// Clear video feed
	video.src = '';
	document.getElementById('statusValue').textContent = 'Stopped';
	resetDashboard();
}

function fetchDetectionData() {
	fetch('/drowsy/api/detection_data')
		.then(response => response.json())
		.then(data => {
			updateDashboard(data);
		})
		.catch(err => {
			console.error('Error fetching detection data:', err);
		});
}

function updateDashboard(data) {
	if (!data) return;

	let fatigueScore = data.fatigue_score || 0;
	let ear = (data.ear || 0.3).toFixed(2);
	let mar = (data.mar || 0.5).toFixed(2);
	let status = data.status || 'NORMAL';
	let alarm = data.alarm || false;
	let alarmDuration = data.alarm_duration || 0;
	let isYawning = data.is_yawning || false;

	// Update all dashboard values
	document.getElementById('fatigueScore').textContent = fatigueScore;
	document.getElementById('earValue').textContent = ear;
	document.getElementById('marValue').textContent = mar;

	// Update status
	let statusIndicator = document.getElementById('statusIndicator');
	let statusValue = document.getElementById('statusValue');
	let alarmStatus = document.getElementById('alarmStatus');

	if (fatigueScore >= 70 || status === 'CRITICAL') {
		statusIndicator.className = 'status-indicator danger';
		statusValue.textContent = 'CRITICAL';
		statusValue.style.color = '#f44336';

		if (alarm) {
			alarmStatus.textContent = `ACTIVE (${alarmDuration}s)`;
			alarmStatus.style.color = '#f44336';
			alarmStatus.style.webkitTextFillColor = '#f44336';
			alarmStatus.style.background = 'none';

			// Play alarm sound
			if (alarmAudio.paused) {
				alarmAudio.play().catch(e => console.error("Audio play failed:", e));
			}
		} else {
			alarmStatus.textContent = 'Monitoring';
			alarmStatus.style.color = '#fff';
			alarmStatus.style.webkitTextFillColor = 'initial';
			alarmStatus.style.background = 'initial';
			alarmAudio.pause();
		}
	} else if (fatigueScore > 50 || status === 'MODERATE') {
		statusIndicator.className = 'status-indicator warning';
		statusValue.textContent = 'MODERATE';
		statusValue.style.color = '#FF9800';
		alarmStatus.textContent = 'Monitoring';
		alarmStatus.style.color = '#fff';
		alarmAudio.pause();
	} else {
		statusIndicator.className = 'status-indicator';
		statusValue.textContent = 'NORMAL';
		statusValue.style.color = '#fff';
		alarmStatus.textContent = 'Inactive';
		alarmStatus.style.color = '#fff';
		alarmAudio.pause();
	}

	// Additional info display
	if (isYawning) {
		statusValue.textContent += ' - Yawning Detected';
	}
}

function resetDashboard() {
	document.getElementById('fatigueScore').textContent = '0';
	document.getElementById('earValue').textContent = '0.00';
	document.getElementById('marValue').textContent = '0.00';
	document.getElementById('statusValue').textContent = 'Stopped';
	document.getElementById('alarmStatus').textContent = 'Inactive';
	document.getElementById('statusIndicator').className = 'status-indicator';
	alarmAudio.pause();
	alarmAudio.currentTime = 0;
}

// Cleanup on page unload
window.addEventListener('beforeunload', function () {
	stopDetection();
});
