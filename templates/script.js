function changeMode() {

    document.body.classList.toggle("dark");

    let button = document.getElementById("modeBtn");

    if (document.body.classList.contains("dark")) {

        button.innerHTML = "☀️ Light Mode";

    } else {

        button.innerHTML = "🌙 Dark Mode";

    }
}