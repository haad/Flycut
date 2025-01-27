# How to develop Flycut mac app

**Develop Environs:**

1. Xcode

**Flycut mac app project desc:**

Flycut mac app include Flycut helper and Flycut app. Other dependence frameworks like MJCloudKit and other system frameworks.

**Develop:**

1. Open project by Xcode clone

2. Change build settings, if you don't have a apple develop account, you will need to ignore project signature signing, cloud and push settings. If your mac os version is high, you might need to change the minimum os version.

3. Comment out related MJCloudKit code.

4. In my case, Build phases - Set meaningful build number is not working. So I comment it out.

5. Build and run, if you have no apple develop account, you will need to run it in your mac. Not sure the apple signing strategy.
