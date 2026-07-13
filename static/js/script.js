document.addEventListener("DOMContentLoaded", function () {

    console.log("☕ CoffeeHouse UI Loaded");

    // =========================
    // SMOOTH PAGE FADE EFFECT
    // =========================
    document.body.style.opacity = "0";
    setTimeout(() => {
        document.body.style.transition = "0.6s ease";
        document.body.style.opacity = "1";
    }, 100);

    // =========================
    // AUTO SCROLL CHAT (if exists)
    // =========================
    const chatWindow = document.getElementById("chat-window");
    if (chatWindow) {
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    // =========================
    // INPUT FOCUS EFFECT
    // =========================
    const inputs = document.querySelectorAll("input");

    inputs.forEach(input => {
        input.addEventListener("focus", () => {
            input.style.transform = "scale(1.02)";
        });

        input.addEventListener("blur", () => {
            input.style.transform = "scale(1)";
        });
    });

});