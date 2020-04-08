import board, neopixel

length = 32

pixels = neopixel.NeoPixel(board.D21, length, pixel_order=neopixel.GRB)
pixels.fill((0, 0, 0))
