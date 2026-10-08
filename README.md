Скрипт для генерации правил RoutingA для обхода российских блокировок на основе данных opencck.org. Фактически представляет из себя надстройку над RoutingA, поддерживающую обращение к opencck и резолвинг доменов по IP. Поддерживает только ipv4! Если ваш провайдер поставляет ipv6 наравне с ipv4 (так делают мобильные, например), отключите ipv6 в настройках сети вашего устройства.

## Логика подстановки

Доступные функции в подстановке (имена описательные, т.е. не дублируют имена реальных дататипов python):
- resolve(String url) -> Dictionary<String>
- exclude(Dictionary<String> toExclude, Dictionary<String> dict) -> Dictionary<String>
- toIp(Dictionary<String> domains): резолвит DNS записи, поддерживает minecraft srv
- lists.<ваш_список> -> Dictionary<String> и vars.<ваша_строка> -> String
- Dictionary<String> + Dictionary<String> right -> Dictionary<String>
- finalize(Dictionary<String>) -> String: неявная функция конвертирующая возвращаемое значение {{}} в строку. То есть код внутри {{}} должен возвращать Dictionary<String>, не String.

rules и .cache не находятся в gitignore в целях отказоустойчивости, чтобы даже если чё-то не сработало все нужные данные поставлялись вместе с репозиторием.