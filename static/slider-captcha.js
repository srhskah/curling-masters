// 滑块验证码组件
class SliderCaptcha {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            width: 300,
            height: 40,
            sliderWidth: 40,
            ...options
        };
        this.isVerified = false;
        this.init();
    }

    init() {
        this.createHTML();
        this.bindEvents();
    }

    createHTML() {
        this.container.innerHTML = `
            <div class="slider-captcha-container" style="width: ${this.options.width}px; height: ${this.options.height}px;">
                <div class="slider-track" style="width: 100%; height: 100%; background: #f0f0f0; border-radius: 20px; position: relative; border: 1px solid #ddd;">
                    <div class="slider-text" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #999; font-size: 14px; user-select: none;">
                        拖动滑块完成验证
                    </div>
                    <div class="slider-button" style="width: ${this.options.sliderWidth}px; height: ${this.options.height - 4}px; background: #fff; border: 1px solid #ddd; border-radius: 18px; position: absolute; top: 2px; left: 2px; cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <div class="slider-icon" style="width: 20px; height: 20px; background: #007bff; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
                            <span style="color: white; font-size: 12px;">→</span>
                        </div>
                    </div>
                </div>
                <div class="slider-success" style="display: none; color: #28a745; font-size: 14px; text-align: center; margin-top: 10px;">
                    ✓ 验证成功
                </div>
            </div>
        `;
    }

    bindEvents() {
        const button = this.container.querySelector('.slider-button');
        const track = this.container.querySelector('.slider-track');
        const text = this.container.querySelector('.slider-text');
        const success = this.container.querySelector('.slider-success');

        let isDragging = false;
        let startX = 0;
        let currentX = 0;

        button.addEventListener('mousedown', (e) => {
            if (this.isVerified) return;
            isDragging = true;
            startX = e.clientX;
            button.style.transition = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging || this.isVerified) return;
            
            currentX = e.clientX - startX;
            const maxX = this.options.width - this.options.sliderWidth - 4;
            
            if (currentX < 0) currentX = 0;
            if (currentX > maxX) currentX = maxX;
            
            button.style.left = currentX + 2 + 'px';
            
            // 更新进度
            const progress = currentX / maxX;
            if (progress > 0.8) {
                track.style.background = 'linear-gradient(to right, #28a745 0%, #28a745 ' + (progress * 100) + '%, #f0f0f0 ' + (progress * 100) + '%, #f0f0f0 100%)';
            } else {
                track.style.background = 'linear-gradient(to right, #007bff 0%, #007bff ' + (progress * 100) + '%, #f0f0f0 ' + (progress * 100) + '%, #f0f0f0 100%)';
            }
        });

        document.addEventListener('mouseup', () => {
            if (!isDragging || this.isVerified) return;
            isDragging = false;
            
            const maxX = this.options.width - this.options.sliderWidth - 4;
            const progress = currentX / maxX;
            
            if (progress >= 0.9) {
                // 验证成功
                this.verifySuccess();
            } else {
                // 验证失败，重置
                this.reset();
            }
        });

        // 触摸事件支持
        button.addEventListener('touchstart', (e) => {
            if (this.isVerified) return;
            isDragging = true;
            startX = e.touches[0].clientX;
            button.style.transition = 'none';
            e.preventDefault();
        });

        document.addEventListener('touchmove', (e) => {
            if (!isDragging || this.isVerified) return;
            
            currentX = e.touches[0].clientX - startX;
            const maxX = this.options.width - this.options.sliderWidth - 4;
            
            if (currentX < 0) currentX = 0;
            if (currentX > maxX) currentX = maxX;
            
            button.style.left = currentX + 2 + 'px';
            
            const progress = currentX / maxX;
            if (progress > 0.8) {
                track.style.background = 'linear-gradient(to right, #28a745 0%, #28a745 ' + (progress * 100) + '%, #f0f0f0 ' + (progress * 100) + '%, #f0f0f0 100%)';
            } else {
                track.style.background = 'linear-gradient(to right, #007bff 0%, #007bff ' + (progress * 100) + '%, #f0f0f0 ' + (progress * 100) + '%, #f0f0f0 100%)';
            }
        });

        document.addEventListener('touchend', () => {
            if (!isDragging || this.isVerified) return;
            isDragging = false;
            
            const maxX = this.options.width - this.options.sliderWidth - 4;
            const progress = currentX / maxX;
            
            if (progress >= 0.9) {
                this.verifySuccess();
            } else {
                this.reset();
            }
        });
    }

    verifySuccess() {
        this.isVerified = true;
        const button = this.container.querySelector('.slider-button');
        const track = this.container.querySelector('.slider-track');
        const text = this.container.querySelector('.slider-text');
        const success = this.container.querySelector('.slider-success');
        const icon = this.container.querySelector('.slider-icon');

        button.style.transition = 'all 0.3s ease';
        button.style.left = (this.options.width - this.options.sliderWidth - 2) + 'px';
        track.style.background = '#28a745';
        text.style.display = 'none';
        success.style.display = 'block';
        icon.innerHTML = '✓';
        icon.style.background = '#28a745';

        // 触发验证成功事件
        this.container.dispatchEvent(new CustomEvent('captchaSuccess', {
            detail: { verified: true }
        }));
    }

    reset() {
        this.isVerified = false;
        const button = this.container.querySelector('.slider-button');
        const track = this.container.querySelector('.slider-track');
        const text = this.container.querySelector('.slider-text');
        const success = this.container.querySelector('.slider-success');
        const icon = this.container.querySelector('.slider-icon');

        button.style.transition = 'all 0.3s ease';
        button.style.left = '2px';
        track.style.background = '#f0f0f0';
        text.style.display = 'block';
        success.style.display = 'none';
        icon.innerHTML = '→';
        icon.style.background = '#007bff';
    }

    isVerified() {
        return this.isVerified;
    }

    destroy() {
        this.container.innerHTML = '';
    }
}

// 全局函数，方便使用
window.createSliderCaptcha = function(containerId, options) {
    return new SliderCaptcha(containerId, options);
};
