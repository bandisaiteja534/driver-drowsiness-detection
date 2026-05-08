// Graphs Page JavaScript
// Add click event listeners to all graph cards
document.addEventListener('DOMContentLoaded', function() {
	const graphCards = document.querySelectorAll('.graph-card');
	graphCards.forEach(function(card) {
		card.addEventListener('click', function() {
			const imageSrc = this.getAttribute('data-image');
			const title = this.getAttribute('data-title');
			openZoomModal(imageSrc, title);
		});
	});
});

function openZoomModal(imageSrc, title) {
	const modal = document.getElementById('zoomModal');
	const modalImage = document.getElementById('zoomedImage');
	const modalTitle = document.getElementById('zoomedTitle');
	
	modalImage.src = imageSrc;
	modalTitle.textContent = title;
	modal.classList.add('active');
	document.body.style.overflow = 'hidden'; // Prevent background scrolling
}

function closeZoomModal(event) {
	// Only close if clicking on the modal background or close button
	if (event.target.id === 'zoomModal' || event.target.classList.contains('zoom-modal-close')) {
		const modal = document.getElementById('zoomModal');
		modal.classList.remove('active');
		document.body.style.overflow = 'auto'; // Restore scrolling
	}
}

// Close modal on Escape key
document.addEventListener('keydown', function(event) {
	if (event.key === 'Escape') {
		const modal = document.getElementById('zoomModal');
		if (modal.classList.contains('active')) {
			modal.classList.remove('active');
			document.body.style.overflow = 'auto';
		}
	}
});
