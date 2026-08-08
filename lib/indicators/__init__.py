"""指標プラグインの自動登録。

このパッケージをimportするだけで、配下の全モジュールの@register()付き関数が
lib.indicators.registryに登録される。新しい指標ファイルを追加したら、ここにも
1行追加する(自動探索はせず、明示的にimportする方針)。
"""

from lib.indicators import candle  # noqa: F401
from lib.indicators import ema  # noqa: F401
from lib.indicators import high_low  # noqa: F401
from lib.indicators import momentum  # noqa: F401
from lib.indicators import volume  # noqa: F401
